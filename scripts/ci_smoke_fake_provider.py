"""Fake OpenAI-compatible provider for the frozen-bundle smoke test.

v1.2.11 follow-up: the release smoke gate needs to prove that ONE AI-chat
Arabic tool call actually executes INSIDE the PyInstaller bundle - without an
Ollama/LM Studio/cloud dependency. This script plays the model:

  round 1 (no tool message in the request): return a tool_calls response
           asking for `arabic_morphology` on a short MSA sentence;
  round 2 (a role=tool message IS present): verify the tool result carries a
           REAL CAMeL morphology analysis (the root of كتب - the root itself
           or its \\uXXXX JSON escapes - plus Buckwalter output), then return
           a final content string the smoke script greps for.

Any other call (the confidence layer's chat_json, for instance) gets a
well-formed JSON reply so nothing upstream crashes.

Run:  python3 ci_smoke_fake_provider.py <port>
Stdout is quiet by design; the smoke script talks HTTP to 127.0.0.1:<port>/v1.
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8791

TOOL_TEXT = "الكتب المفيدة في المكتبة"
# Root of كتب in literal form and in JSON-escaped form (json.dumps defaults
# to ensure_ascii=True, so the tool message may carry either).
ROOT_MARKERS = ["ك.ت.ب", "\\u0643.\\u062a.\\u0628"]
# Buckwalter of one of the tokens (kutub / kutubun etc. all start with "ktb")
BUCKWALTER_MARKER = "ktb"

_last_reason = ["no tool message seen yet"]


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # /v1/models — health checks + model listing
        self._send(
            {
                "object": "list",
                "data": [{"id": "smoke-fake", "object": "model", "owned_by": "smoke"}],
            }
        )

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        req = json.loads(self.rfile.read(length) or b"{}")
        messages = req.get("messages", [])

        tool_content = ""
        for m in messages:
            if m.get("role") == "tool":
                tool_content = m.get("content", "") or ""
                break

        if tool_content:
            ok = any(marker in tool_content for marker in ROOT_MARKERS) and (
                BUCKWALTER_MARKER in tool_content.lower()
            )
            if ok:
                content = f"SMOKE_ARABIC_TOOL_OK root found in tool result ({len(tool_content)} chars)"
            else:
                content = f"SMOKE_ARABIC_TOOL_FAIL: tool result lacked the expected morphology ({_last_reason[0]}): {tool_content[:200]}"
            self._send(
                {
                    "id": "smoke-final",
                    "object": "chat.completion",
                    "model": req.get("model", "smoke-fake"),
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": content},
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
            )
            return

        # JSON-mode calls (confidence layer / query suggestions) get valid
        # JSON so their parsers never choke.
        fmt = req.get("response_format") or {}
        if fmt.get("type") == "json_object":
            self._send(
                {
                    "id": "smoke-json",
                    "object": "chat.completion",
                    "model": req.get("model", "smoke-fake"),
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(
                                    {
                                        "confidence": 0.9,
                                        "supporting_evidence_ids": [],
                                        "unsupported_claims": [],
                                        "reasoning": "smoke",
                                    }
                                ),
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
            )
            return

        # Round 1: ask for the Arabic morphology tool.
        _last_reason[0] = "tool call issued"
        self._send(
            {
                "id": "smoke-round1",
                "object": "chat.completion",
                "model": req.get("model", "smoke-fake"),
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "arabic_morphology",
                                        "arguments": json.dumps({"text": TOOL_TEXT}),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        )

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"fake provider listening on 127.0.0.1:{PORT}", flush=True)
    server.serve_forever()
