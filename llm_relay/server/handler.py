"""
HTTP request handler.

Receives OpenAI Responses API calls from the client (e.g. Codex CLI),
orchestrates the translation pipeline, and returns either a JSON response
or a Server-Sent Events (SSE) stream.

Design: dependency injection via class factory
----------------------------------------------
``BaseHTTPRequestHandler`` is instantiated by ``HTTPServer`` on every request —
we cannot override its ``__init__`` signature to inject dependencies.  The
standard Python solution is a *class factory*: ``make_handler()`` creates a
new class that closes over the shared dependencies as class-level attributes.
This gives us:

  - Full dependency injection (no globals, no singletons).
  - Easy unit testing: construct the class directly with mock dependencies.
  - A clean separation between HTTP plumbing and business logic.

SSE simulation
--------------
The backend (DeepSeek) is called in non-streaming mode: we receive the full
response as a single JSON payload.  When the client requests streaming, we
*simulate* SSE by replaying the completed response as a sequence of events
that matches the real OpenAI Responses API streaming protocol.

This avoids partial-JSON parsing complexity and keeps the translator layer
stateless, while still letting streaming-aware clients (like Codex CLI) work
exactly as they expect.

Supported endpoints
-------------------
  GET  /health              — Liveness probe (returns ``{"status": "ok"}``).
  POST /responses           — Main proxy endpoint.
  POST /v1/responses        — Alias for compatibility with OpenAI SDK base-URL
                              configurations that include the version prefix.
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
    """
    Create and return a ``BaseHTTPRequestHandler`` subclass with the given
    dependencies baked in as class-level attributes.

    This factory is called once at server startup.  The returned class is
    passed to ``HTTPServer`` and re-instantiated on every incoming request,
    but the dependencies are shared across all instances (thread-safe because
    ``SessionStore`` uses an internal lock and ``Config`` is frozen).

    Args:
        config:        Immutable runtime configuration.
        session_store: Thread-safe conversation history store.
        translator:    Backend translator (e.g. ``DeepSeekTranslator``).

    Returns:
        A ``BaseHTTPRequestHandler`` subclass ready for use with ``HTTPServer``.
    """

    class ProxyHandler(BaseHTTPRequestHandler):
        """
        Per-request HTTP handler for the llm-relay proxy.

        Attributes (class-level, shared across all instances):
            _config:        Runtime configuration.
            _session_store: Conversation history repository.
            _translator:    Backend translator implementation.
        """

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
            """
            Main proxy endpoint.

            Pipeline:
            1. Read and parse the request body.
            2. Reconstruct conversation history from the session store.
            3. Translate tools from Responses API format to Chat Completions.
            4. Build and forward the backend request.
            5. Parse the backend response.
            6. Persist the updated session.
            7. Return JSON or simulate SSE streaming.
            """
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
            """
            Reconstruct the full conversation history for this request.

            If ``previous_response_id`` is present and known to the session
            store, the stored history is prepended to the new input items.
            Otherwise, a fresh conversation is started (instructions included).

            function_call deduplication
            ---------------------------
            The Responses API spec requires clients to echo the model's
            ``function_call`` output items back in the next request's
            ``input[]``, alongside the ``function_call_output`` results.
            Because the session store already contains those tool calls as
            the last assistant message, we drop any ``function_call`` items
            from ``input[]`` when appending to existing history — keeping them
            would produce a duplicate assistant/tool_calls message that
            violates the Chat Completions ordering rule and triggers a 400.

            History trimming: when the combined history exceeds
            ``config.max_history_messages``, the oldest messages are discarded
            while always preserving the system message at index 0 (so the
            agent's identity and rules are never silently dropped).
            """
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
            """
            Write a single Server-Sent Events frame to the response stream.

            SSE format::

                event: <name>\\n
                data: <json>\\n
                \\n
            """
            frame = f"event: {event}\ndata: {json.dumps(data)}\n\n"
            self.wfile.write(frame.encode())
            self.wfile.flush()

        def _stream_response(self, response: dict, req_id: str) -> None:
            """
            Simulate an OpenAI Responses API SSE stream from a complete response.

            Even though the backend was called in non-streaming mode, Codex CLI
            expects the streaming event sequence.  We replay the completed
            response as the exact sequence of events the real API would emit.

            Event sequence per output item:
              - ``response.created``
              - For each item → ``response.output_item.added``
                  - For text items → content_part.added / text.delta / text.done
                                     / content_part.done
                  - For tool calls → function_call_arguments.delta / .done
              - For each item → ``response.output_item.done``
              - ``response.completed``
            """
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
