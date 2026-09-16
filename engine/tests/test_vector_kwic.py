"""Vector KWIC tests (v1.2.0, item 4) — mocked deterministic embedder.

The embedder is replaced with a deterministic hash-based vectorizer so the
tests exercise the full pipeline (candidate search → context embedding →
cache reuse → cosine ranking) without Ollama. The deterministic embedder
maps tokens to dimensions, so semantically overlapping contexts genuinely
score higher — the ranking assertions are meaningful, not vacuous.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

# Canonical in-memory-DB env (mirrors test_api.py) BEFORE engine imports.
os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-vector-kwic"
os.environ["CORPUSMIND_OLLAMA_BASE_URL"] = "http://127.0.0.1:1"  # no real Ollama


# --------------------------------------------------------------------------- #
# Deterministic mock embedder
# --------------------------------------------------------------------------- #

DIM = 64


def _token_vec(token: str) -> dict[int, float]:
    import hashlib

    h = hashlib.md5(token.encode("utf-8")).digest()
    return {h[0] % DIM: 1.0 + (h[1] % 10) / 10.0, h[2] % DIM: -0.5 - (h[3] % 10) / 10.0}


def _embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for tok in text.lower().split():
        for k, v in _token_vec(tok.strip(".,!?")).items():
            vec[k] += v
    return vec


@dataclass
class FakeEmbeddingResponse:
    vector: list[float]
    model: str = "test-embed"
    provider: str = "ollama"


class FakeOllamaProvider:
    """Minimal provider double: deterministic embed + installed-model list."""

    name = "ollama"

    def __init__(self, installed: list[str] | None = None):
        self.installed = installed if installed is not None else ["test-embed"]
        self.embed_calls: list[str] = []

    async def list_models(self):
        return list(self.installed)

    async def embed(self, text: str, *, model: str | None = None, timeout: float | None = None):
        self.embed_calls.append(text)
        return FakeEmbeddingResponse(vector=_embed(text), model=model or "test-embed")


class MissingModelProvider(FakeOllamaProvider):
    """list_models says the model is absent → the API must 409 with a hint."""

    async def embed(self, text: str, *, model: str | None = None, timeout: float | None = None):
        raise RuntimeError(f"[ollama] embed failed: model '{model}' not found")


# --------------------------------------------------------------------------- #
# Fixtures: app + seeded corpus (3 sentences sharing the node "climate")
# --------------------------------------------------------------------------- #


async def _seed_corpus(session_factory):
    """Seed project + corpus + docs + annotation version + tokens."""
    from storage.models import AnnotationVersion, Corpus, Document, Project, Token

    async with session_factory() as s:
        p = Project(name="P", language="en")
        s.add(p)
        await s.flush()
        c = Corpus(project_id=p.id, name="Weather corpus", language="en")
        s.add(c)
        await s.flush()
        v = AnnotationVersion(corpus_id=c.id, version_label="v1", model_name="test")
        s.add(v)
        await s.flush()

        docs = {
            "d1": "Climate change affects agriculture. The climate of Europe is mild. Policies on climate vary by country.",
            "d2": "Rising temperatures harm crops. Farmers worry about the changing climate. Hot weather reduces yields.",
        }
        for name, text in docs.items():
            d = Document(corpus_id=c.id, filename=f"{name}.txt", cleaned_text=text)
            s.add(d)
            await s.flush()
            for sent_idx, sentence in enumerate(text.split(". ")):
                toks = [t for t in sentence.replace(".", " ").split() if t]
                for tok_idx, tok in enumerate(toks):
                    s.add(Token(
                        version_id=v.id,
                        document_id=d.id,
                        sentence_idx=sent_idx,
                        token_idx=tok_idx,
                        text=tok,
                        lemma=tok.lower(),
                        pos="NOUN" if tok.lower() in ("climate", "weather") else "WORD",
                        dep_rel="dep",
                    ))
        await s.commit()
        return c.id


@pytest.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    import storage.session as _ss
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            # Seed AFTER lifespan (init_db has created the tables), then
            # inject the fake provider into the freshly-built registry.
            cid = await _seed_corpus(_ss._sessionmaker)
            fake = FakeOllamaProvider()
            app.state.providers._instances["ollama"] = fake
            yield ac, cid, fake
    await dispose_db()


@pytest.fixture
async def client_missing_model():
    from httpx import ASGITransport, AsyncClient

    import storage.session as _ss
    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            cid = await _seed_corpus(_ss._sessionmaker)
            fake = MissingModelProvider()
            app.state.providers._instances["ollama"] = fake
            yield ac, cid
    await dispose_db()


# --------------------------------------------------------------------------- #
# Pure-function tests
# --------------------------------------------------------------------------- #


def test_cosine_identical_and_orthogonal():
    from semantic.vector_kwic import cosine

    v = _embed("climate change affects agriculture")
    assert cosine(v, v) == pytest.approx(1.0, abs=1e-9)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([], []) == 0.0


def test_resolve_embed_model_chain(monkeypatch):
    from semantic import vector_kwic as vk

    assert vk.resolve_embed_model("custom-embed") == "custom-embed"   # request wins
    assert vk.resolve_embed_model(None) == "bge-m3"                    # settings default
    monkeypatch.setenv("CORPUSMIND_EMBEDDING_MODEL", "env-embed")
    from app.settings import get_settings

    get_settings.cache_clear()
    assert vk.resolve_embed_model(None) == "env-embed"                 # env wins over default
    get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# API tests (mocked embedder through the FastAPI app)
# --------------------------------------------------------------------------- #


async def test_vector_kwic_mode_a_ranks_and_orders(client):
    ac, cid, _fake = client
    r = await ac.post(f"/api/v1/corpora/{cid}/concordance/vector", json={
        "query": "climate change effects on farming and crops",
        "node": "climate",
        "window": 6,
        "top_k": 10,
        "model": "test-embed",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mode"] == "keyword"
    assert data["model"] == "test-embed"
    assert data["total"] > 0
    sims = [line["similarity"] for line in data["lines"]]
    assert sims == sorted(sims, reverse=True)  # ranked descending
    assert all("similarity" in line and "left" in line and "node" in line for line in data["lines"])
    # The agriculture/crops sentence should outrank the "Policies on climate
    # vary by country" sentence for this query (deterministic embedder).
    nodes = [line["right"] for line in data["lines"]]
    assert any("agriculture" in n for n in nodes[:2])
    assert "cosine" in data["note"].lower()


async def test_vector_kwic_mode_b_semantic_search(client):
    ac, cid, _fake = client
    r = await ac.post(f"/api/v1/corpora/{cid}/concordance/vector", json={
        "query": "farmers and crop harvests",
        "node": None,
        "top_k": 3,
        "model": "test-embed",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mode"] == "semantic"
    assert data["scanned"] > 0
    assert len(data["lines"]) <= 3
    assert data["lines"][0]["similarity"] >= data["lines"][-1]["similarity"]


async def test_vector_kwic_cache_reuse(client):
    """Second identical query must hit the cache — zero new embed calls for
    the line contexts (only the query itself gets embedded again)."""
    ac, cid, fake = client
    body = {"query": "climate policy", "node": "climate", "window": 6, "model": "test-embed"}
    r1 = await ac.post(f"/api/v1/corpora/{cid}/concordance/vector", json=body)
    assert r1.status_code == 200
    calls_after_first = len(fake.embed_calls)
    r2 = await ac.post(f"/api/v1/corpora/{cid}/concordance/vector", json=body)
    assert r2.status_code == 200
    # Only +1 (the query embedding) — contexts came from kwic_vector_cache.
    assert len(fake.embed_calls) == calls_after_first + 1


async def test_vector_kwic_missing_model_409_with_hint(client_missing_model):
    ac, cid = client_missing_model
    r = await ac.post(f"/api/v1/corpora/{cid}/concordance/vector", json={
        "query": "anything", "node": "climate",
    })
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["error"] == "embedding_model_missing"
    assert "ollama pull" in detail["hint"]
    assert detail["model"]


async def test_vector_kwic_untagged_pull_matches_bare_model(client):
    """Regression (v1.2.2): real Ollama registers an untagged pull as
    'bge-m3:latest' in /api/tags. Both the API-layer pre-flight and the
    engine-internal check must compare canonical names, so a bare 'bge-m3'
    request succeeds when the ':latest' variant is installed. The v1.2.1
    fix canonicalized only the engine-internal check; this API pre-flight
    kept returning 409 right after a successful download."""
    ac, cid, fake = client
    fake.installed = ["llama3.2:3b", "bge-m3:latest"]  # what real Ollama reports
    r = await ac.post(f"/api/v1/corpora/{cid}/concordance/vector", json={
        "query": "climate policy", "node": "climate", "model": "bge-m3",
    })
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "bge-m3"


async def test_vector_kwic_corpus_missing_404(client):
    ac, _cid, _fake = client
    r = await ac.post("/api/v1/corpora/does-not-exist/concordance/vector", json={
        "query": "x", "node": "y",
    })
    assert r.status_code == 404
