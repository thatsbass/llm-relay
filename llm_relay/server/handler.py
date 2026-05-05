"""
HTTP request handler for the llm-relay proxy.

Supported endpoints:
  GET  /health        — Liveness probe.
  POST /responses     — Main proxy endpoint.
  POST /v1/responses  — Alias for OpenAI SDK base-URL compatibility.
"""

from __future__ import annotations

import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError

from llm_relay.config import Config
from llm_relay.parsers.messages import input_to_messages, translate_tools
from llm_relay.session.store import SessionStore
from llm_relay.translators.base import AbstractTranslator


# ── Handler factory ───────────────────────────────────────────────────────────


def make_handler(
    config: Config,
    session_store: SessionStore,
    translator: AbstractTranslator,
) -> type:
    """Return a BaseHTTPRequestHandler subclass with dependencies baked in as class attributes."""

    class ProxyHandler(BaseHTTPRequestHandler):
        """Per-request HTTP handler for the llm-relay proxy."""

        _config:        Config              = config
        _session_store: SessionStore        = session_store
        _translator:    AbstractTranslator  = translator

        # ── Logging ───────────────────────────────────────────────────────────

        def log_message(self, fmt: str, *args) -> None:
            """Suppress standard HTTP access logs unless debug mode is on."""
            if self._config.debug:
                sys.stderr.write(f"[llm-relay] {args[0]}\n")

        # ── GET /health ───────────────────────────────────────────────────────

        def do_GET(self) -> None:
            """Health check endpoint — returns HTTP 200 with ``{"status":"ok"}``."""
            if self.path == "/health":
                self._send_json_direct({"status": "ok"})
            else:
                self.send_error(404, f"Not found: {self.path}")

        # ── POST /responses ───────────────────────────────────────────────────

        def do_POST(self) -> None:
            """Proxy a Responses API request to the backend and return the translated response."""
            if self.path not in ("/responses", "/v1/responses"):
                self.send_error(404, f"Unknown path: {self.path}")
                return

            # ── 1. Read body ──────────────────────────────────────────────────
            length   = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length)
            req_id   = f"resp_{uuid.uuid4().hex[:24]}"

            try:
                req_data = json.loads(raw_body)
            except json.JSONDecodeError:
                self.send_error(400, "Request body is not valid JSON")
                return

            # ── 2. Build message history ──────────────────────────────────────
            messages = self._build_messages(req_data)

            # ── 3. Translate tools ────────────────────────────────────────────
            tools  = translate_tools(req_data.get("tools"))
            stream = req_data.get("stream", False)

            max_tokens = req_data.get(
                "max_output_tokens", self._config.max_output_tokens
            )

            # Count assistant tool-call turns to detect potential loops.
            tc_count = sum(
                1 for m in messages
                if m.get("tool_calls") or m.get("role") == "tool"
            )

            if self._config.debug:
                self._log_request(req_id, messages, tc_count, stream, tools)

            # ── 4–5. Forward to backend and parse response ────────────────────
            try:
                payload = self._translator.build_request(
                    messages, tools, max_tokens, tc_count,
                    temperature=req_data.get("temperature"),
                    top_p=req_data.get("top_p"),
                )
                raw_resp = self._translator.forward(json.dumps(payload).encode())
                result   = self._translator.parse_response(raw_resp, req_id)

            except HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")
                print(
                    f"[llm-relay] Upstream HTTP {exc.code}: {err_body[:500]}",
                    file=sys.stderr,
                )
                if exc.code == 400:
                    self._log_messages_debug(messages)
                self.send_error(502, f"Upstream error: {exc.code}")
                return

            except URLError as exc:
                print(f"[llm-relay] Connection error: {exc.reason}", file=sys.stderr)
                self.send_error(502, f"Connection error: {exc.reason}")
                return

            except Exception as exc:
                import traceback
                traceback.print_exc(file=sys.stderr)
                self.send_error(500, str(exc))
                return

            # ── 6. Persist session ────────────────────────────────────────────
            self._save_session(req_id, messages, result.assistant_message)

            if self._config.debug:
                self._log_response(result.response)

            # ── 7. Respond to client ──────────────────────────────────────────
            if stream:
                self._stream_response(result.response, req_id)
            else:
                self._send_json_direct(result.response, extra_headers={"x-request-id": req_id})

        # ── Session management ────────────────────────────────────────────────

        def _build_messages(self, req_data: dict) -> list:
            """Reconstruct full conversation history, prepending session store if available."""
            prev_id = req_data.get("previous_response_id")

            if prev_id:
                history = self._session_store.get(prev_id)
                if history is not None:
                    # Drop function_call items — the session history already
                    # contains the matching assistant{tool_calls} message.
                    new_input = [
                        item for item in req_data.get("input", [])
                        if item.get("type") != "function_call"
                    ]
                    new_msgs = input_to_messages(new_input)
                    combined = history + new_msgs

                    if len(combined) > self._config.max_history_messages:
                        # Preserve system message + most recent N messages.
                        sys_msg = (
                            combined[0]
                            if combined and combined[0]["role"] == "system"
                            else None
                        )
                        tail     = combined[-self._config.history_trim_to:]
                        combined = ([sys_msg] if sys_msg else []) + tail

                    return combined

            # No prior session — build from scratch with full input.
            return input_to_messages(
                req_data.get("input", []),
                req_data.get("instructions"),
            )

        def _save_session(
            self,
            req_id: str,
            messages: list,
            assistant_message: dict,
        ) -> None:
            """Append the assistant turn to history and persist under *req_id*."""
            self._session_store.save(req_id, messages + [assistant_message])

        # ── SSE streaming ─────────────────────────────────────────────────────

        def _emit(self, event: str, data: dict) -> None:
            """Write a single SSE frame to the response stream."""
            frame = f"event: {event}\ndata: {json.dumps(data)}\n\n"
            self.wfile.write(frame.encode())
            self.wfile.flush()

        def _stream_response(self, response: dict, req_id: str) -> None:
            """Simulate an OpenAI Responses API SSE stream from the completed response."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("x-request-id", req_id)
            self.end_headers()

            # Signal that the response has been created (status=in_progress).
            self._emit("response.created", {
                "type":     "response.created",
                "response": {**response, "status": "in_progress", "output": []},
            })

            for out_idx, item in enumerate(response.get("output", [])):
                item_type = item.get("type")
                item_id   = item.get("id", f"item_{out_idx}")

                if item_type == "message":
                    self._stream_message_item(item, item_id, out_idx)

                elif item_type == "function_call":
                    self._stream_function_call_item(item, item_id, out_idx)

            self._emit("response.completed", {
                "type":     "response.completed",
                "response": response,
            })

        def _stream_message_item(
            self, item: dict, item_id: str, out_idx: int
        ) -> None:
            """Emit the SSE event sequence for a text message output item."""
            self._emit("response.output_item.added", {
                "type":         "response.output_item.added",
                "output_index": out_idx,
                "item":         {**item, "status": "in_progress", "content": []},
            })

            for ci, part in enumerate(item.get("content", [])):
                text        = part.get("text", "")
                annotations = part.get("annotations", [])

                self._emit("response.content_part.added", {
                    "type":          "response.content_part.added",
                    "item_id":       item_id,
                    "output_index":  out_idx,
                    "content_index": ci,
                    "part": {"type": "output_text", "text": "", "annotations": annotations},
                })

                if text:
                    self._emit("response.output_text.delta", {
                        "type":          "response.output_text.delta",
                        "item_id":       item_id,
                        "output_index":  out_idx,
                        "content_index": ci,
                        "delta":         text,
                    })
                    self._emit("response.output_text.done", {
                        "type":          "response.output_text.done",
                        "item_id":       item_id,
                        "output_index":  out_idx,
                        "content_index": ci,
                        "text":          text,
                    })

                self._emit("response.content_part.done", {
                    "type":          "response.content_part.done",
                    "item_id":       item_id,
                    "output_index":  out_idx,
                    "content_index": ci,
                    "part": {"type": "output_text", "text": text, "annotations": annotations},
                })

            self._emit("response.output_item.done", {
                "type":         "response.output_item.done",
                "output_index": out_idx,
                "item":         item,
            })

        def _stream_function_call_item(
            self, item: dict, item_id: str, out_idx: int
        ) -> None:
            """Emit the SSE event sequence for a function-call output item."""
            self._emit("response.output_item.added", {
                "type":         "response.output_item.added",
                "output_index": out_idx,
                "item":         {**item, "status": "in_progress"},
            })

            args = item.get("arguments", "")
            if args:
                self._emit("response.function_call_arguments.delta", {
                    "type":         "response.function_call_arguments.delta",
                    "item_id":      item_id,
                    "output_index": out_idx,
                    "delta":        args,
                })
                self._emit("response.function_call_arguments.done", {
                    "type":         "response.function_call_arguments.done",
                    "item_id":      item_id,
                    "output_index": out_idx,
                    "arguments":    args,
                })

            self._emit("response.output_item.done", {
                "type":         "response.output_item.done",
                "output_index": out_idx,
                "item":         item,
            })

        # ── Response helpers ──────────────────────────────────────────────────

        def _send_json_direct(
            self, body: dict, extra_headers: dict | None = None
        ) -> None:
            """Send a JSON response with HTTP 200."""
            encoded = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(encoded)

        # ── Debug logging ─────────────────────────────────────────────────────

        def _log_request(
            self,
            req_id: str,
            messages: list,
            tc_count: int,
            stream: bool,
            tools: list | None,
        ) -> None:
            print(
                f"\n{'=' * 60} {req_id}\n"
                f"  messages={len(messages)}  tool_turns={tc_count}"
                f"  tools={len(tools or [])}  stream={stream}",
                file=sys.stderr,
            )

        def _log_response(self, response: dict) -> None:
            output   = response.get("output", [])
            fn_calls = [o for o in output if o.get("type") == "function_call"]
            print(
                f"  → {len(fn_calls)} tool call(s), "
                f"{len(output) - len(fn_calls)} text message(s)",
                file=sys.stderr,
            )

        def _log_messages_debug(self, messages: list) -> None:
            """Dump the messages array on upstream 400 to help diagnose ordering issues."""
            print("[llm-relay] Messages sent to backend (400 debug):", file=sys.stderr)
            for i, m in enumerate(messages):
                role     = m.get("role", "?")
                tcs      = m.get("tool_calls")
                tc_ids   = [tc.get("id", "?") for tc in tcs] if tcs else []
                tc_id    = m.get("tool_call_id", "")
                content  = str(m.get("content") or "")[:60].replace("\n", "↵")
                if tc_ids:
                    print(f"  [{i:02d}] {role}  tool_call_ids={tc_ids}", file=sys.stderr)
                elif tc_id:
                    print(f"  [{i:02d}] {role}  tool_call_id={tc_id!r}  content={content!r}", file=sys.stderr)
                else:
                    print(f"  [{i:02d}] {role}  content={content!r}", file=sys.stderr)

    return ProxyHandler
