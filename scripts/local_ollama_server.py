#!/usr/bin/env python3
"""
Fazle Core — local Ollama-compatible model server (fallback runtime).

WHY THIS EXISTS
---------------
Fazle Core talks to a local LLM through exactly two Ollama endpoints
(`app/ollama_daemon.py`):

    GET  /api/tags      — used by app/ollama.check_ollama_health(), by the
                          /health probe, and by app/llm.py's Hermes-family
                          model resolver
    POST /api/generate  — every reply/classify/RAG call, payload:
                          {"model", "prompt", "stream": false, "options": {...}}
                          and the reply text is read from `response`

A normal deployment runs the real Ollama daemon (`ollama serve`). On a machine
where ollama.com / registry.ollama.ai are unreachable (air-gapped CI, a
restricted egress sandbox, a laptop behind a proxy), that is not possible — but
the two endpoints above are trivial to serve from llama.cpp directly. This
process implements them on top of a local GGUF file so the app's local-AI path
stays live instead of silently degrading to the fallback string.

This is NOT a full Ollama reimplementation: no model pulling, no Modelfiles, no
/api/chat streaming semantics beyond the basics, no GPU offload policy beyond
llama.cpp's own. If you have real Ollama, run real Ollama — this is the
fallback for when you cannot.

USAGE
-----
    python scripts/local_ollama_server.py \
        --model-file /home/user/fazle-local/models/gemma-3-270m-q4_k_m.gguf \
        --model-name gemma3-270m \
        --host 127.0.0.1 --port 11434

Then point Fazle Core at it:

    OLLAMA_URL=http://127.0.0.1:11434
    OLLAMA_MODEL=gemma3-270m

The model name is served verbatim in /api/tags, so whatever you pass as
--model-name must match OLLAMA_MODEL.

REQUIREMENTS
------------
    pip install llama-cpp-python fastapi uvicorn
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any

# Imported at module level on purpose: FastAPI resolves string annotations (this
# file uses `from __future__ import annotations`) against module globals, so a
# function-local `from fastapi import Request` makes FastAPI think `request` is a
# query parameter and every call 422s.
from fastapi import Request  # noqa: F401

log = logging.getLogger("fazle.local_ollama")

# ── Model runtime ────────────────────────────────────────────────────────────
# One llama.cpp context per process. Every generation is serialized through
# this lock -- llama.cpp contexts are not thread-safe, and that also matches
# Fazle Core's own inference policy (OLLAMA_INFER_CONCURRENCY defaults to 1
# because concurrent requests on a small CPU box time out).
_LLM = None
_LOCK = threading.Lock()
_MODEL_NAME = "local-model"
_MODEL_PATH = ""
_LOAD_ERROR = ""


def _load_model(path: str, n_ctx: int, n_threads: int) -> None:
    global _LLM, _LOAD_ERROR
    try:
        from llama_cpp import Llama
    except Exception as exc:  # pragma: no cover - environment dependent
        _LOAD_ERROR = f"llama_cpp unavailable: {type(exc).__name__}: {exc}"
        log.error(_LOAD_ERROR)
        return
    t0 = time.time()
    try:
        _LLM = Llama(
            model_path=path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_batch=128,
            verbose=False,
        )
        log.info(
            "[local_ollama] loaded %s (%s, n_ctx=%d, threads=%d) in %.1fs",
            _MODEL_NAME, os.path.basename(path), n_ctx, n_threads, time.time() - t0,
        )
    except Exception as exc:
        _LOAD_ERROR = f"load failed: {type(exc).__name__}: {exc}"
        log.error("[local_ollama] %s", _LOAD_ERROR)


def _generate_sync(prompt: str, options: dict[str, Any]) -> tuple[str, dict]:
    """Run one completion. Returns (text, stats). Caller must hold _LOCK."""
    if _LLM is None:
        raise RuntimeError(_LOAD_ERROR or "model not loaded")
    max_tokens = int(options.get("num_predict") or 128)
    # Ollama convention: num_predict = -1 means "until context is full".
    if max_tokens < 0:
        max_tokens = 512
    t0 = time.time()
    out = _LLM(
        prompt,
        max_tokens=max_tokens,
        temperature=float(options.get("temperature") or 0.7),
        top_p=float(options.get("top_p") or 0.9),
        stop=options.get("stop") or None,
        echo=False,
    )
    elapsed = time.time() - t0
    text = ""
    usage = {}
    try:
        text = (out["choices"][0]["text"] or "").strip()
        usage = out.get("usage") or {}
    except Exception:
        text = ""
    stats = {
        "total_duration": int(elapsed * 1e9),
        "eval_count": int(usage.get("completion_tokens") or 0),
        "prompt_eval_count": int(usage.get("prompt_tokens") or 0),
    }
    return text, stats


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── HTTP layer ───────────────────────────────────────────────────────────────
def build_app(model_file: str, model_name: str, n_ctx: int, n_threads: int):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

    global _MODEL_NAME, _MODEL_PATH
    _MODEL_NAME = model_name
    _MODEL_PATH = model_file

    app = FastAPI(title="Local Ollama-compatible server", docs_url=None, redoc_url=None)

    _load_model(model_file, n_ctx, n_threads)

    def _size() -> int:
        try:
            return os.path.getsize(model_file)
        except OSError:
            return 0

    def _tags() -> dict:
        return {
            "models": [
                {
                    "name": _MODEL_NAME,
                    "model": _MODEL_NAME,
                    "modified_at": _now_iso(),
                    "size": _size(),
                    "digest": "",
                    "details": {
                        "format": "gguf",
                        "family": "gemma3",
                        "parameter_size": "270M",
                        "quantization_level": "Q4_K_M",
                    },
                }
            ]
        }

    @app.get("/", response_class=PlainTextResponse)
    async def root():
        return "Ollama is running"

    @app.get("/api/version")
    async def version():
        return {"version": "local-llama-cpp-1.0"}

    @app.get("/api/tags")
    async def tags():
        return _tags()

    @app.get("/api/ps")
    async def ps():
        return {"models": [] if _LLM is None else [{"name": _MODEL_NAME, "size": _size()}]}

    def _pick_model(requested: str | None) -> str:
        # Be permissive: Fazle Core may ask for OLLAMA_MODEL, or (from
        # app/llm.py's resolver) one of the hermes3-family tags. We serve one
        # model; answering under whatever name was asked keeps the caller's
        # own logic intact instead of forcing an env change.
        return requested or _MODEL_NAME

    @app.post("/api/generate")
    async def generate(request: Request):
        body = await request.json()
        prompt = body.get("prompt") or ""
        options = body.get("options") or {}
        name = _pick_model(body.get("model"))
        if not prompt.strip():
            return JSONResponse({"error": "empty prompt"}, status_code=400)
        if _LLM is None:
            return JSONResponse(
                {"error": _LOAD_ERROR or "model not loaded"}, status_code=503
            )

        def _run():
            with _LOCK:
                return _generate_sync(prompt, options)

        text, stats = await asyncio.get_running_loop().run_in_executor(None, _run)

        payload = {
            "model": name,
            "created_at": _now_iso(),
            "response": text,
            "done": True,
            "done_reason": "stop",
            **stats,
        }
        if not body.get("stream"):
            return payload

        async def _stream():
            yield json.dumps({**payload, "response": text, "done": False}) + "\n"
            yield json.dumps({**payload, "response": "", "done": True}) + "\n"

        return StreamingResponse(_stream(), media_type="application/x-ndjson")

    @app.post("/api/chat")
    async def chat(request: Request):
        body = await request.json()
        messages = body.get("messages") or []
        options = body.get("options") or {}
        name = _pick_model(body.get("model"))
        if _LLM is None:
            return JSONResponse(
                {"error": _LOAD_ERROR or "model not loaded"}, status_code=503
            )
        # Flatten to a single prompt: the model served here is a base
        # completion model, and Fazle Core only ever sends one prompt string.
        parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            parts.append(content if role == "user" else f"{role}: {content}")
        prompt = "\n".join(p for p in parts if p)

        def _run():
            with _LOCK:
                return _generate_sync(prompt, options)

        text, stats = await asyncio.get_running_loop().run_in_executor(None, _run)
        payload = {
            "model": name,
            "created_at": _now_iso(),
            "message": {"role": "assistant", "content": text},
            "done": True,
            "done_reason": "stop",
            **stats,
        }
        if not body.get("stream"):
            return payload

        async def _stream():
            yield json.dumps({**payload, "done": False}) + "\n"
            yield json.dumps({**payload, "message": {"role": "assistant", "content": ""}, "done": True}) + "\n"

        return StreamingResponse(_stream(), media_type="application/x-ndjson")

    @app.post("/api/show")
    async def show(request: Request):
        body = await request.json()
        return {
            "modelfile": f"FROM {model_file}",
            "parameters": f"num_ctx {n_ctx}",
            "details": _tags()["models"][0]["details"],
            "model_info": {"general.name": body.get("model") or _MODEL_NAME},
        }

    @app.post("/api/embeddings")
    async def embeddings(request: Request):
        # Not used by Fazle Core's reply chain (RAG uses sentence-transformers
        # / BM25), but a 501 is clearer than a 404 if something does call it.
        return JSONResponse(
            {"error": "embeddings are not served by this fallback runtime"},
            status_code=501,
        )

    return app


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1] if __doc__ else "")
    ap.add_argument("--model-file", required=True, help="path to a local .gguf file")
    ap.add_argument("--model-name", default="", help="name served in /api/tags (default: file stem)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11434)
    ap.add_argument("--n-ctx", type=int, default=2048)
    ap.add_argument(
        "--n-threads",
        type=int,
        default=max(1, (os.cpu_count() or 2) - 1),
        help="llama.cpp threads (leave one core for the app)",
    )
    ap.add_argument("--log-level", default="info")
    args = ap.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not os.path.isfile(args.model_file):
        log.error("model file not found: %s", args.model_file)
        return 2
    name = args.model_name or os.path.splitext(os.path.basename(args.model_file))[0]

    import uvicorn

    app = build_app(args.model_file, name, args.n_ctx, args.n_threads)
    log.info("[local_ollama] serving model=%s on %s:%d", name, args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
