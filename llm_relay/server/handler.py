"""
HTTP request handler for the llm-relay proxy.

Supported endpoints:
  GET  /health        — Liveness probe.
  GET  /v1/models     — Anthropic model list (Claude Desktop auto-discovery).
  POST /responses     — Main proxy endpoint (OpenAI Responses API).
  POST /v1/responses  — Alias for OpenAI SDK base-URL compatibility.
  POST /v1/messages   — Anthropic Messages API (Claude Code / Desktop).
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError

from llm_relay.config import Config
from llm_relay.models import get_models_for_backend
from llm_relay.parsers.anthropic_messages import parse_anthropic_request
from llm_relay.parsers.messages import input_to_messages, translate_tools
from llm_relay.routing.engine import RoutingEngine
from llm_relay.session.store import SessionStore
from llm_relay.translators.base import AbstractTranslator


# ── Handler factory ───────────────────────────────────────────────────────────


def make_handler(
    config: Config,
    session_store: SessionStore,
    routing: RoutingEngine,
) -> type:
    """Return a BaseHTTPRequestHandler subclass with dependencies baked in as class attributes."""

    class ProxyHandler(BaseHTTPRequestHandler):
        """Per-request HTTP handler for the llm-relay proxy."""

        _config:        Config        = config
        _session_store: SessionStore  = session_store
        _routing:       RoutingEngine = routing

        # ── Logging ───────────────────────────────────────────────────────────

        def log_message(self, fmt: str, *args) -> None:
            """Always emit HTTP access logs (method path status) to stderr."""
            sys.stderr.write(f"[access] {self.log_date_time_string()} {fmt % args}\n")
            sys.stderr.flush()

        # ── GET /health ───────────────────────────────────────────────────────

        def do_GET(self) -> None:
            """Health check + model list for auto-discovery."""
            path = self.path.split("?")[0]
            if path == "/health":
                self._send_json_direct({"status": "ok"})
            elif path == "/v1/models":
                self._handle_models()
            elif path == "/":
                self._send_json_direct({"status": "ok", "version": "0.2.0"})
            else:
                self.send_error(404, f"Not found: {self.path}")

        def do_HEAD(self) -> None:
            """Respond to HEAD requests the same as GET."""
            path = self.path.split("?")[0]
            if path in ("/health", "/v1/models", "/"):
                self.send_response(200)
                self.end_headers()
            else:
                self.send_error(404)

        def _handle_models(self) -> None:
            """Return available models in Anthropic format."""
            ids = get_models_for_backend(self._config.backend)
            models = [
                {"id": mid, "type": "model", "display_name": mid,
                 "created_at": "2026-01-01T00:00:00Z"}
                for mid in ids
            ]
            self._send_json_direct({
                "data": models,
                "has_more": False,
                "first_id": ids[0] if ids else "",
                "last_id": ids[-1] if ids else "",
            })

        # ── POST /responses ───────────────────────────────────────────────────

        def do_POST(self) -> None:
            """Proxy a request to the backend and return the translated response."""
            path = self.path.split("?")[0]
            if path in ("/responses", "/v1/responses"):
                self._handle_responses()
            elif path == "/v1/messages":
                self._handle_anthropic()
            elif path == "/v1/messages/count_tokens":
                self._handle_count_tokens()
            else:
                self.send_error(404, f"Unknown path: {self.path}")

        # ── POST /responses ────────────────────────────────────────────────

        def _handle_responses(self) -> None:
            """Proxy a Responses API request to the backend."""
            # ── 1. Read body
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

            model = req_data.get("model", "?")
            print(
                f"[req] {req_id}  path=/responses  backend={self._config.backend}"
                f"  model={model}  msgs={len(messages)}  tools={len(tools or [])}  stream={stream}",
                file=sys.stderr, flush=True,
            )

            if self._config.debug:
                self._log_request(req_id, messages, tc_count, stream, tools)

            # ── 4–5. Forward to backend and parse response ────────────────────
            t0 = time.monotonic()
            try:
                payload = self._routing.build_request(
                    messages, tools, max_tokens, tc_count,
                    temperature=req_data.get("temperature"),
                    top_p=req_data.get("top_p"),
                )
                raw_resp = self._routing.forward(json.dumps(payload).encode())
                result   = self._routing.parse_response(raw_resp, req_id)
                elapsed  = time.monotonic() - t0
                usage    = result.response.get("usage", {})
                print(
                    f"[ok]  {req_id}  {elapsed:.1f}s"
                    f"  in={usage.get('input_tokens', '?')} out={usage.get('output_tokens', '?')}",
                    file=sys.stderr, flush=True,
                )

            except HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")
                print(
                    f"[err] {req_id}  upstream HTTP {exc.code}: {err_body[:300]}",
                    file=sys.stderr, flush=True,
                )
                if exc.code == 400:
                    self._log_messages_debug(messages)
                self.send_error(502, f"Upstream error: {exc.code}")
                return

            except URLError as exc:
                print(f"[err] {req_id}  connection error: {exc.reason}", file=sys.stderr, flush=True)
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

        # ── POST /v1/messages ─────────────────────────────────────────────

        def _handle_anthropic(self) -> None:
            """Proxy an Anthropic Messages API request to the backend."""
            length   = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length)

            try:
                req_data = json.loads(raw_body)
            except json.JSONDecodeError:
                self.send_error(400, "Request body is not valid JSON")
                return

            parsed = parse_anthropic_request(req_data)
            stream = parsed.stream

            req_id = f"msg_{uuid.uuid4().hex[:16]}"
            print(
                f"[req] {req_id}  path=/v1/messages  backend={self._config.backend}"
                f"  model={parsed.model}  msgs={len(parsed.messages)}"
                f"  tools={len(parsed.tools or [])}  stream={stream}"
                f"  pass_through={self._routing.has_pass_through()}",
                file=sys.stderr, flush=True,
            )

            # ── Pass-through path ──────────────────────────────────────
            if self._routing.has_pass_through():
                t0 = time.monotonic()
                try:
                    payload  = self._routing.build_anthropic_request(req_data)
                    raw_resp = self._routing.forward(payload)
                    result   = self._routing.parse_anthropic_response(
                        raw_resp, f"msg_{uuid.uuid4().hex[:24]}",
                    )
                    elapsed = time.monotonic() - t0
                    usage   = result.response.get("usage", {})
                    print(
                        f"[ok]  {req_id}  {elapsed:.1f}s  [pass-through]"
                        f"  in={usage.get('input_tokens','?')} out={usage.get('output_tokens','?')}",
                        file=sys.stderr, flush=True,
                    )
                except HTTPError as exc:
                    err_body = exc.read().decode("utf-8", errors="replace")
                    print(f"[err] {req_id}  upstream HTTP {exc.code}: {err_body[:300]}", file=sys.stderr, flush=True)
                    self.send_error(502, f"Upstream error: {exc.code}")
                    return
                except URLError as exc:
                    print(f"[err] {req_id}  connection error: {exc.reason}", file=sys.stderr, flush=True)
                    self.send_error(502, f"Connection error: {exc.reason}")
                    return
                except Exception as exc:
                    import traceback
                    traceback.print_exc(file=sys.stderr)
                    self.send_error(500, str(exc))
                    return

                if stream:
                    self._stream_anthropic_response(result.response)
                else:
                    self._send_json_direct(result.response)
                return

            # ── Translation path: Anthropic → Chat Completions ──────────
            t0 = time.monotonic()
            try:
                payload  = self._routing.build_request(
                    parsed.messages, parsed.tools, parsed.max_tokens,
                    0,
                    temperature=parsed.temperature,
                    top_p=parsed.top_p,
                    model=parsed.model,
                )
                raw_resp = self._routing.forward(json.dumps(payload).encode())
                result   = self._routing.parse_response(raw_resp, f"msg_{uuid.uuid4().hex[:24]}")
                elapsed  = time.monotonic() - t0
                usage    = result.response.get("usage", {})
                print(
                    f"[ok]  {req_id}  {elapsed:.1f}s  [translate→chat_completions]"
                    f"  in={usage.get('input_tokens','?')} out={usage.get('output_tokens','?')}",
                    file=sys.stderr, flush=True,
                )
            except HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")
                print(f"[err] {req_id}  upstream HTTP {exc.code}: {err_body[:300]}", file=sys.stderr, flush=True)
                self.send_error(502, f"Upstream error: {exc.code}")
                return
            except URLError as exc:
                print(f"[err] {req_id}  connection error: {exc.reason}", file=sys.stderr, flush=True)
                self.send_error(502, f"Connection error: {exc.reason}")
                return
            except Exception as exc:
                import traceback
                traceback.print_exc(file=sys.stderr)
                self.send_error(500, str(exc))
                return

            if stream:
                self._stream_anthropic_response(result.response)
            else:
                self._send_json_direct(result.response)

        # ── POST /v1/messages/count_tokens (Claude Desktop token counting) ─

        def _handle_count_tokens(self) -> None:
            """Handle Claude Desktop's token-counting probe."""
            self._send_json_direct({"input_tokens": 0})

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
            self.send_header("Connection", "close")
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

        # ── Anthropic SSE streaming ──────────────────────────────────────────

        def _stream_anthropic_response(self, response: dict) -> None:
            """Simulate an Anthropic Messages SSE stream from the completed response."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            msg_id  = response.get("id", f"msg_{uuid.uuid4().hex[:12]}")
            model   = response.get("model", "unknown")
            output  = response.get("output", [])
            usage   = response.get("usage", {})

            # message_start
            self._emit("message_start", {
                "type": "message_start",
                "message": {
                    "id": msg_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": 0,
                    },
                },
            })

            block_index = 0
            for item in output:
                item_type = item.get("type")

                if item_type == "message":
                    text = ""
                    for part in item.get("content", []):
                        if part.get("type") == "output_text":
                            text += part.get("text", "")
                    if text:
                        self._emit("content_block_start", {
                            "type": "content_block_start",
                            "index": block_index,
                            "content_block": {"type": "text", "text": ""},
                        })
                        self._emit("content_block_delta", {
                            "type": "content_block_delta",
                            "index": block_index,
                            "delta": {"type": "text_delta", "text": text},
                        })
                        self._emit("content_block_stop", {
                            "type": "content_block_stop",
                            "index": block_index,
                        })
                        block_index += 1

                elif item_type == "function_call":
                    fn   = item.get("name", "")
                    args = item.get("arguments", "")
                    tool_id = item.get("call_id", f"toolu_{uuid.uuid4().hex[:12]}")
                    try:
                        tool_input = json.loads(args) if args else {}
                    except json.JSONDecodeError:
                        tool_input = {"arguments": args}

                    self._emit("content_block_start", {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {"type": "tool_use", "id": tool_id, "name": fn, "input": {}},
                    })
                    # Send the input JSON delta
                    input_json = json.dumps(tool_input)
                    self._emit("content_block_delta", {
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {"type": "input_json_delta", "partial_json": input_json},
                    })
                    self._emit("content_block_stop", {
                        "type": "content_block_stop",
                        "index": block_index,
                    })
                    block_index += 1

            # message_delta
            self._emit("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": usage.get("output_tokens", 0)},
            })

            # message_stop
            self._emit("message_stop", {"type": "message_stop"})

            # Signal end of chunked body and close so the client stops waiting.
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

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
