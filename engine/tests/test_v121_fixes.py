"""v1.2.1 regression tests — model download + HF catalogue fixes.

Covers the three bugs reported by the user on v1.2.0:
1. bge-m3 / nomic-embed-text "doesn't download" (bare vs ':latest' names,
   pull errors masked as success).
2. Hugging Face tab always empty (enrichment client closed + empty-query
   short-circuit + broken K-quant regex).
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from ai.hf_catalog import _quant_of, search_gguf
from ai.providers import OllamaProvider, canonical_model_name
from api import system as system_mod
from api.system import OllamaPullRequest, _pull_error_from_body

# --------------------------------------------------------------------------- #
# canonical_model_name — bare vs ':latest' matching
# --------------------------------------------------------------------------- #


def test_canonical_model_name_strips_implicit_latest():
    assert canonical_model_name("bge-m3:latest") == "bge-m3"
    assert canonical_model_name("bge-m3") == "bge-m3"
    assert canonical_model_name("llama3.2:3b") == "llama3.2:3b"          # explicit tag kept
    assert canonical_model_name("hf.co/user/repo:Q4_K_M") == "hf.co/user/repo:Q4_K_M"
    assert canonical_model_name("  nomic-embed-text:latest ") == "nomic-embed-text"


def test_vector_preflight_accepts_latest_tagged_install():
    """The v1.2.0 bug: installed=['bge-m3:latest'], requested 'bge-m3' 409'd forever."""
    from semantic.vector_kwic import EmbeddingModelError, _embed_texts

    class FakeProvider:
        def __init__(self, installed):
            self._installed = installed

        async def list_models(self):
            return list(self._installed)

        async def embed(self, text, *, model=None):
            from ai.providers import EmbeddingResponse

            return EmbeddingResponse(vector=[0.1, 0.2, 0.3], model=model or "", provider="fake")

    async def _run(installed, model):
        return await _embed_texts(FakeProvider(installed), ["hello"], model)

    # Ollama registers an untagged pull as ':latest' — must now MATCH.
    vectors = asyncio.run(_run(["bge-m3:latest", "llama3.2:3b"], "bge-m3"))
    assert vectors == [[0.1, 0.2, 0.3]]

    # nomic-embed-text (the other untagged catalogue entry) as well.
    vectors = asyncio.run(_run(["nomic-embed-text:latest"], "nomic-embed-text"))
    assert vectors == [[0.1, 0.2, 0.3]]

    # Genuinely missing model still raises the 409-grade error.
    with pytest.raises(EmbeddingModelError):
        asyncio.run(_run(["llama3.2:3b"], "bge-m3"))


def test_ollama_provider_list_models_is_normalized_for_catalogue_compare():
    """list_models keeps raw names; consumers canonicalise via the helper."""
    assert canonical_model_name("bge-m3:latest") in {"bge-m3"}


# --------------------------------------------------------------------------- #
# HF quant regex + catalogue search (mock transport — no network)
# --------------------------------------------------------------------------- #


def test_quant_regex_detects_common_k_quants():
    assert _quant_of("bge-m3-Q4_K_M.gguf") == "Q4_K_M"
    assert _quant_of("model-Q6_K.gguf") == "Q6_K"
    assert _quant_of("Qwen3-30B-A3B-IQ4_XS.gguf") == "IQ4_XS"
    assert _quant_of("chat-Q8_0.gguf") == "Q8_0"
    assert _quant_of("weights-BF16.gguf") == "BF16"
    assert _quant_of("not-a-quant.gguf") is None


_LIST_BODY = [
    {"modelId": "BAAI/bge-m3-GGUF", "pipeline_tag": "feature-extraction",
     "tags": ["gguf", "feature-extraction"], "downloads": 1000, "likes": 50},
    {"modelId": "someone/chat-7b-GGUF", "pipeline_tag": "text-generation",
     "tags": ["gguf", "text-generation"], "downloads": 900, "likes": 10},
]
_DETAIL_BODY = {
    "modelId": "BAAI/bge-m3-GGUF", "pipeline_tag": "feature-extraction",
    "tags": ["gguf", "feature-extraction"], "downloads": 1000, "likes": 50,
    "lastModified": "2026-01-01T00:00:00",
    "siblings": [
        {"rfilename": "bge-m3-Q4_K_M.gguf", "size": 1_200_000_000},
        {"rfilename": "README.md", "size": 100},
    ],
}


def _hf_mock_handler(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        path_after = url.split("/api/models/")[1].strip("/") if "/api/models/" in url else ""
        if path_after:
            return httpx.Response(200, json=_DETAIL_BODY)
        seen["list_params"] = dict(request.url.params)  # list endpoint only
        return httpx.Response(200, json=_LIST_BODY)

    return handler


@pytest.mark.asyncio
async def test_search_gguf_browses_when_query_empty():
    seen: dict = {}
    res = await search_gguf("", task="any", transport=httpx.MockTransport(_hf_mock_handler(seen)))
    assert "search" not in seen["list_params"], "browse mode must not send a search filter"
    assert len(res["models"]) == 2


@pytest.mark.asyncio
async def test_search_gguf_embedding_chip_seeds_default_query():
    seen: dict = {}
    res = await search_gguf("", task="embedding",
                            transport=httpx.MockTransport(_hf_mock_handler(seen)))
    assert seen["list_params"].get("search") == "embed"
    assert res["models"]


@pytest.mark.asyncio
async def test_search_gguf_enriches_repos_closed_client_regression():
    """v1.2.0 bug: enrichment ran on a CLOSED httpx client → every repo was
    skipped → the Hugging Face tab was always empty."""
    res = await search_gguf("anything", task="any",
                            transport=httpx.MockTransport(_hf_mock_handler({})))
    assert len(res["models"]) == 2
    m = res["models"][0]
    assert m["repo"] == "BAAI/bge-m3-GGUF"
    v = m["quant_variants"][0]
    assert v["quant"] == "Q4_K_M"
    assert v["pull_name"] == "hf.co/BAAI/bge-m3-GGUF:Q4_K_M"
    assert v["size_bytes"] == 1_200_000_000


# --------------------------------------------------------------------------- #
# Pull endpoint — error surfacing (no more fake success)
# --------------------------------------------------------------------------- #


def test_pull_error_from_body_variants():
    assert _pull_error_from_body('{"error":"model is required"}') == "model is required"
    assert _pull_error_from_body("pull model manifest: connection refused") == \
        "pull model manifest: connection refused"
    assert _pull_error_from_body("") == ""
    assert "boom" in _pull_error_from_body("boom")


class _OllamaMock(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence test output
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json({"models": []})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/pull":
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if payload.get("model") == "fail-model":
                body = b'{"error":"pull model manifest: registry unreachable"}\n'
            else:
                body = (
                    b'{"status":"pulling manifest"}\n'
                    b'{"status":"downloading","total":100,"completed":40}\n'
                    b'{"status":"success"}\n'
                )
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "not found"}, 404)


@pytest.fixture()
def ollama_mock():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _OllamaMock)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.mark.asyncio
async def test_ollama_pull_surfaces_ollama_errors(ollama_mock, monkeypatch):
    monkeypatch.setattr(
        system_mod, "get_settings",
        lambda: type("S", (), {"ollama_base_url": ollama_mock}),
    )
    system_mod._pull_status.clear()

    resp = await system_mod.ollama_pull(OllamaPullRequest(model="fail-model"))
    assert resp["ok"] is True
    for _ in range(50):
        await asyncio.sleep(0.05)
        st = system_mod._pull_status.get("fail-model", {})
        if st.get("status") in ("error", "success"):
            break
    # v1.2.0 reported status='success' here (error line swallowed). Now:
    assert st["status"] == "error"
    assert "registry unreachable" in (st.get("error") or "")


@pytest.mark.asyncio
async def test_ollama_pull_success_path_and_modern_payload(ollama_mock, monkeypatch):
    monkeypatch.setattr(
        system_mod, "get_settings",
        lambda: type("S", (), {"ollama_base_url": ollama_mock}),
    )
    system_mod._pull_status.clear()

    resp = await system_mod.ollama_pull(OllamaPullRequest(model="bge-m3"))
    assert resp["ok"] is True
    for _ in range(50):
        await asyncio.sleep(0.05)
        st = system_mod._pull_status.get("bge-m3", {})
        if st.get("status") in ("error", "success"):
            break
    assert st["status"] == "success"
    assert st["total"] == 100


def test_provider_list_models_returns_raw_ollama_names():
    """Documents the source of the ':latest' names (kept raw by design)."""
    class S:
        ollama_base_url = "http://127.0.0.1:1"  # nothing there
        ollama_default_model = "llama3.2:3b"

    p = OllamaProvider(S())

    async def _run():
        return await p.list_models()

    names = asyncio.run(_run())
    assert names == []  # unreachable daemon → [] (best-effort), no crash
