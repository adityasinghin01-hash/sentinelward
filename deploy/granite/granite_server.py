"""Minimal OpenAI-compatible server for IBM Granite on LinuxONE (s390x).

Runs inside IBM's LinuxONE Community Cloud lab image, which ships llama-cpp-python and a
big-endian Granite GGUF. Standard library HTTP only, so nothing extra has to be installed.
Listens on 127.0.0.1 only. Endpoints: GET /health, POST /v1/completions, POST /v1/chat/completions.
The agents (A8 shift briefing) send facts and get prose back; they never let it trigger actions.
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llama_cpp import Llama

MAX_TOKENS_CAP = 400
_lock = threading.Lock()  # llama.cpp contexts are not thread-safe


def chat_to_prompt(messages):
    # Granite base models have no chat template; a plain labelled transcript works best.
    lines = []
    for m in messages:
        role = str(m.get("role", "user")).capitalize()
        lines.append(f"{role}: {m.get('content', '')}")
    lines.append("Assistant:")
    return "\n".join(lines)


def make_handler(llm, model_name):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 (base-class name)  # keep request bodies out of logs
            pass

        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"status": "ok", "model": model_name})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            try:
                length = min(int(self.headers.get("Content-Length", 0)), 64_000)
                req = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._send(400, {"error": "invalid JSON"})
                return
            if self.path == "/v1/chat/completions":
                prompt = chat_to_prompt(req.get("messages", []))
            elif self.path == "/v1/completions":
                prompt = str(req.get("prompt", ""))
            else:
                self._send(404, {"error": "not found"})
                return
            max_tokens = max(1, min(int(req.get("max_tokens", 256)), MAX_TOKENS_CAP))
            temperature = float(req.get("temperature", 0.2))
            started = time.time()
            with _lock:
                out = llm(prompt, max_tokens=max_tokens, temperature=temperature,
                          stop=["\nUser:", "\nSystem:"])
            text = out["choices"][0]["text"].strip()
            usage = out.get("usage", {})
            if self.path == "/v1/chat/completions":
                choice = {"index": 0, "message": {"role": "assistant", "content": text},
                          "finish_reason": out["choices"][0].get("finish_reason")}
            else:
                choice = {"index": 0, "text": text,
                          "finish_reason": out["choices"][0].get("finish_reason")}
            self._send(200, {"object": "chat.completion" if "chat" in self.path else "text_completion",
                             "model": model_name, "created": int(started),
                             "choices": [choice], "usage": usage,
                             "latency_ms": int((time.time() - started) * 1000)})

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="path to the Granite .gguf file")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--ctx", type=int, default=2048)
    args = ap.parse_args()
    llm = Llama(model_path=args.model, n_ctx=args.ctx, n_threads=args.threads, verbose=False)
    name = args.model.rsplit("/", 1)[-1]
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(llm, name))
    print(f"Granite server ready on 127.0.0.1:{args.port} model={name}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
