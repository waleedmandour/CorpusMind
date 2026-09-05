"""v1.2.0 Lens round tests — vision model capability selection + upload hardening.

Covers:
  1. Name-heuristic vision detection (_name_suggests_vision).
  2. OllamaProvider.supports_vision / pick_vision_model against mocked
     /api/tags payloads (capabilities present, missing, mixed).
  3. resolve_vision_model() resolution order (explicit > pick > default).
  4. describe endpoint: auto-picked non-vision model → actionable 400;
     vision-capable pick → 200; explicit model bypasses the gate.
  5. Upload hardening: magic-byte rejection, 413 size cap, file-count cap.
  6. read_image_bytes(): decrypt-on-read when encryption is enabled.
"""
from __future__ import annotations

import io
import os
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-visionselect"
from app.settings import get_settings

get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def client():
    from app.main import app
    from storage.session import dispose_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


def _make_test_image(width: int = 80, height: int = 80, color: tuple = (90, 140, 200)) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _setup_image(client: AsyncClient) -> tuple[str, str]:
    """Create project + corpus + image set + one uploaded image."""
    r = await client.post("/api/v1/projects", json={"name": "T", "language": "en"})
    pid = r.json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/corpora", json={"name": "C", "language": "en"})
    cid = r.json()["id"]
    r = await client.post(f"/api/v1/corpora/{cid}/image-sets", json={"name": "S"})
    iset_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("test.png", io.BytesIO(_make_test_image()), "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()[0]["id"], iset_id


def _inject(client: AsyncClient, provider: Any, name: str = "ollama") -> None:
    from app.main import app
    app.state.providers._instances[name] = provider


class _StubProvider:
    """Deterministic provider double with REAL capability methods."""

    name = "ollama"

    def __init__(
        self,
        *,
        models: list[str] | None = None,
        vision_pick: str | None = None,
        vision_map: dict[str, bool] | None = None,
        default_model: str = "",
        healthy: bool = True,
    ) -> None:
        self.models = models if models is not None else ["llama3.2:3b"]
        self.vision_pick = vision_pick
        self.vision_map = vision_map or {}
        self.default_model = default_model
        self.healthy = healthy
        self.chat_calls = 0

    async def health(self) -> bool:
        return self.healthy

    async def list_models(self) -> list[str]:
        return self.models

    async def pick_vision_model(self) -> str | None:
        return self.vision_pick

    async def supports_vision(self, model: str | None = None) -> bool:
        return self.vision_map.get(model or self.default_model, False)

    async def chat(self, messages, **kwargs):
        from ai.providers import ChatResponse
        self.chat_calls += 1
        return ChatResponse(
            content="A described image.",
            model=kwargs.get("model") or self.default_model,
            provider=self.name,
            raw={},
        )

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# 1. Name heuristic
# ---------------------------------------------------------------------------


def test_name_suggests_vision():
    from ai.providers import _name_suggests_vision as v
    assert v("qwen3-vl:2b") is True
    assert v("qwen2.5-vl:7b") is True
    assert v("llama3.2-vision:11b") is True
    assert v("llava:13b") is True
    assert v("moondream") is True
    assert v("minicpm-v:8b") is True
    assert v("gemma3:4b") is True
    assert v("gemma3:1b") is False  # text-only small variant
    assert v("llama3.2:3b") is False
    assert v("nomic-embed-text") is False
    assert v("") is False


# ---------------------------------------------------------------------------
# 2. OllamaProvider capability checks (mocked /api/tags)
# ---------------------------------------------------------------------------


def _settings_for_ollama():
    from app.settings import Settings
    return Settings(
        ollama_base_url="http://test-ollama.invalid:11434",
        ollama_default_model="llama3.2:3b",
        lmstudio_base_url="http://test-lmstudio.invalid:1234/v1",
        lmstudio_default_model="test-model",
    )


def _make_ollama(tags_payload: dict):
    """OllamaProvider whose /api/tags returns the given payload."""
    from ai.providers import OllamaProvider

    provider = OllamaProvider(_settings_for_ollama())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/tags")
        return httpx.Response(200, json=tags_payload)

    original = provider._client
    provider._client = httpx.AsyncClient(
        base_url=original.base_url,
        headers=original.headers,
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(5.0, connect=2.0),
    )
    return provider


@pytest.mark.asyncio
async def test_ollama_supports_vision_with_capabilities():
    p = _make_ollama({"models": [
        {"name": "llama3.2:3b", "capabilities": ["completion", "tools"]},
        {"name": "qwen3-vl:2b", "capabilities": ["vision", "completion"]},
    ]})
    assert await p.supports_vision("qwen3-vl:2b") is True
    assert await p.supports_vision("llama3.2:3b") is False
    # Unknown model → name heuristic
    assert await p.supports_vision("llava:13b") is True
    assert await p.supports_vision("mistral:7b") is False


@pytest.mark.asyncio
async def test_ollama_supports_vision_old_server_falls_back_to_name():
    """Older Ollama without a capabilities field → name heuristic."""
    p = _make_ollama({"models": [{"name": "qwen3-vl:2b"}, {"name": "llama3.2:3b"}]})
    assert await p.supports_vision("qwen3-vl:2b") is True
    assert await p.supports_vision("llama3.2:3b") is False


@pytest.mark.asyncio
async def test_ollama_pick_vision_model_prefers_capability():
    p = _make_ollama({"models": [
        {"name": "llama3.2:3b", "capabilities": ["completion"]},
        {"name": "qwen3-vl:8b", "capabilities": ["vision", "completion"]},
        {"name": "moondream", "capabilities": ["vision"]},
    ]})
    assert await p.pick_vision_model() == "qwen3-vl:8b"


@pytest.mark.asyncio
async def test_ollama_pick_vision_model_name_hint_fallback():
    p = _make_ollama({"models": [{"name": "llama3.2:3b"}, {"name": "bakllava:7b"}]})
    assert await p.pick_vision_model() == "bakllava:7b"


@pytest.mark.asyncio
async def test_ollama_pick_vision_model_none_when_only_text():
    p = _make_ollama({"models": [
        {"name": "llama3.2:3b", "capabilities": ["completion", "tools"]},
        {"name": "nomic-embed-text", "capabilities": ["embedding"]},
    ]})
    assert await p.pick_vision_model() is None


# ---------------------------------------------------------------------------
# 3. resolve_vision_model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_explicit_model_wins():
    from ai.providers import resolve_vision_model
    stub = _StubProvider(vision_pick="qwen3-vl:2b", default_model="llama3.2:3b")
    assert await resolve_vision_model(stub, "my-model") == "my-model"


@pytest.mark.asyncio
async def test_resolve_uses_vision_pick():
    from ai.providers import resolve_vision_model
    stub = _StubProvider(vision_pick="qwen3-vl:2b", default_model="llama3.2:3b")
    assert await resolve_vision_model(stub, None) == "qwen3-vl:2b"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_default_for_mockdoubles():
    """MagicMock-style doubles whose pick_vision_model isn't awaitable
    must fall through to default_model (legacy behavior)."""
    from ai.providers import resolve_vision_model
    mock = MagicMock()
    mock.default_model = "moondream"
    mock.pick_vision_model = MagicMock(return_value=MagicMock())  # non-awaitable
    assert await resolve_vision_model(mock, None) == "moondream"


@pytest.mark.asyncio
async def test_resolve_returns_none_when_nothing_available():
    from ai.providers import resolve_vision_model
    stub = _StubProvider(models=[], vision_pick=None, default_model="")
    assert await resolve_vision_model(stub, None) is None


# ---------------------------------------------------------------------------
# 4. describe endpoint gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_rejects_non_vision_auto_pick(client):
    img_id, _ = await _setup_image(client)
    _inject(client, _StubProvider(
        models=["llama3.2:3b"],
        vision_pick="llama3.2:3b",
        vision_map={"llama3.2:3b": False},
        default_model="llama3.2:3b",
    ))
    r = await client.post(f"/api/v1/images/{img_id}/describe")
    assert r.status_code == 400, r.text
    assert "does not support image input" in r.json()["detail"]
    assert "qwen3-vl:2b" in r.json()["detail"]  # actionable hint


@pytest.mark.asyncio
async def test_describe_uses_vision_capable_pick(client):
    img_id, _ = await _setup_image(client)
    stub = _StubProvider(
        models=["llama3.2:3b", "qwen3-vl:2b"],
        vision_pick="qwen3-vl:2b",
        vision_map={"qwen3-vl:2b": True},
        default_model="llama3.2:3b",
    )
    _inject(client, stub)
    r = await client.post(f"/api/v1/images/{img_id}/describe")
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "qwen3-vl:2b"
    assert stub.chat_calls == 1


@pytest.mark.asyncio
async def test_describe_explicit_model_bypasses_gate(client):
    img_id, _ = await _setup_image(client)
    stub = _StubProvider(
        models=["qwen3-vl:2b"],
        vision_pick="qwen3-vl:2b",
        vision_map={"some-text-model": False},
        default_model="qwen3-vl:2b",
    )
    _inject(client, stub)
    r = await client.post(f"/api/v1/images/{img_id}/describe", json={"model": "some-text-model"})
    assert r.status_code == 200, r.text  # explicit pick is honored
    assert stub.chat_calls == 1


@pytest.mark.asyncio
async def test_describe_proceeds_when_capability_unknown(client):
    """Provider whose supports_vision raises (legacy doubles) → old path."""
    img_id, _ = await _setup_image(client)

    class _Legacy(_StubProvider):
        async def supports_vision(self, model=None):
            raise TypeError("not implemented")

    stub2 = _Legacy(models=["moondream"], vision_pick="moondream", default_model="moondream")
    _inject(client, stub2)
    r = await client.post(f"/api/v1/images/{img_id}/describe")
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "moondream"


# ---------------------------------------------------------------------------
# 5. Upload hardening
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_fake_image_by_magic_bytes(client):
    _, iset_id = await _setup_image(client)
    fake = b"this is definitely not an image, just plain text padding padding" * 4
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("fake.png", io.BytesIO(fake), "image/png")},
    )
    assert r.status_code == 400, r.text
    assert "magic-byte" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_extension_mismatch(client):
    _, iset_id = await _setup_image(client)
    png = _make_test_image()
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("actually-png.jpg", io.BytesIO(png), "image/jpeg")},
    )
    assert r.status_code == 400, r.text
    assert "Rename the file" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_oversized_image(client):
    _, iset_id = await _setup_image(client)
    big = _make_test_image() + b"\x00" * (26 * 1024 * 1024)  # valid PNG header, > 25 MB
    r = await client.post(
        f"/api/v1/image-sets/{iset_id}/images",
        files={"files": ("big.png", io.BytesIO(big), "image/png")},
    )
    assert r.status_code == 413, r.text
    assert "per-image limit" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_too_many_files(client):
    _, iset_id = await _setup_image(client)
    files = [
        ("files", (f"img{i}.png", io.BytesIO(_make_test_image()), "image/png"))
        for i in range(51)
    ]
    r = await client.post(f"/api/v1/image-sets/{iset_id}/images", files=files)
    assert r.status_code == 400, r.text
    assert "Too many files" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upload_still_accepts_real_png(client):
    _, iset_id = await _setup_image(client)  # _setup_image itself uploads a real PNG
    r = await client.get(f"/api/v1/image-sets/{iset_id}/images")
    assert r.status_code == 200
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# 6. read_image_bytes (encryption-aware)
# ---------------------------------------------------------------------------


def test_read_image_bytes_passthrough_without_encryption(tmp_path):
    from vision.pipeline import read_image_bytes
    p = tmp_path / "img.png"
    payload = b"\x89PNG\r\n\x1a\nfake-but-plain"
    p.write_bytes(payload)
    assert read_image_bytes(str(p)) == payload


def test_read_image_bytes_decrypts_when_enabled(tmp_path, monkeypatch):
    from storage import encryption as enc
    from vision.pipeline import read_image_bytes

    key = os.urandom(32)
    monkeypatch.setattr(enc, "get_encryption_key", lambda: key)

    plain = b"\x89PNG\r\n\x1a\nsecret-pixels"
    cipher = enc.encrypt_file(plain, key=key)
    assert cipher != plain  # actually encrypted

    p = tmp_path / "img.png"
    p.write_bytes(cipher)
    assert read_image_bytes(str(p)) == plain

