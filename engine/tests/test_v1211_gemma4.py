"""Gemma 4 catalogue + capability tests (v1.2.11, workstream B).

Facts verified from authoritative sources on 2026-10-07:
  * ollama.com/library/gemma4 (+ /tags): tags gemma4(:latest|=e4b), :e2b,
    :e4b, :12b, :26b (MoE A4B), :31b, :cloud, quant variants
    (:e2b-it-qat, :e2b-it-q4_K_M, :e4b-it-qat, :e4b-it-q4_K_M,
    :12b-it-qat, :12b-it-q4_K_M, -it-q8_0, -it-bf16, -mlx);
    capabilities vision/tools/thinking/audio; 128K (e2b/e4b) and
    256K (12b+) context windows.
  * ai.google.dev/gemma/docs/core/model_card_4: Apache-2.0 license;
    "over 140 languages" pre-trained, 35+ out-of-the-box.
  * NOT verified anywhere authoritative: a minimum Ollama version for the
    gemma4 architecture — the engine therefore classifies version-related
    failures at runtime instead of hardcoding a fabricated number.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from ai.providers import OllamaProvider, canonical_model_name, model_name_matches
from api.system import RECOMMENDED_OLLAMA_MODELS
from app.settings import get_settings

GEMMA4_TAGS = ("gemma4:latest", "gemma4:e2b", "gemma4:e4b", "gemma4:12b", "gemma4:26b", "gemma4:31b")


class TestCatalogue:
    def test_gemma4_entries_present_with_real_tags(self) -> None:
        names = {m["name"] for m in RECOMMENDED_OLLAMA_MODELS}
        for tag in ("gemma4:e2b", "gemma4:e4b", "gemma4:12b"):
            assert tag in names, f"{tag} missing from the catalogue"

    def test_gemma4_entries_carry_fit_badge_data(self) -> None:
        for m in RECOMMENDED_OLLAMA_MODELS:
            if m["name"].startswith("gemma4"):
                assert isinstance(m["size_bytes"], int) and m["size_bytes"] > 0
                assert m["task"] == "text"
                assert m["ram"], "RAM hint needed for the Settings card"

    def test_gemma4_multilingual_claim_is_marked(self) -> None:
        """The verified fact is '140+ languages pre-trained'; the corpus
        languages this release adds must appear in the languages list."""
        e4b = next(m for m in RECOMMENDED_OLLAMA_MODELS if m["name"] == "gemma4:e4b")
        for lang in ("en", "ar", "ur", "hi", "fa"):
            assert lang in e4b["languages"]

    def test_no_fabricated_minimum_version_claim(self) -> None:
        """Catalogue text must not claim a minimum Ollama version (it is
        not verifiable); the runtime error classifier handles it instead."""
        for m in RECOMMENDED_OLLAMA_MODELS:
            if m["name"].startswith("gemma4"):
                assert "requires ollama" not in m["description"].lower()
                assert "minimum ollama" not in m["description"].lower()


class TestGemma4QatCard:
    """v1.2.12: the gemma3:27b card is replaced by gemma4:12b-it-qat.

    Facts verified from the authoritative tag page on 2026-10-09
    (ollama.com/library/gemma4:12b-it-qat):
      * tag exists and pulls natively by name;
      * "model arch gemma4 · parameters 11.9B · quantization Q4_0 · 7.0GB"
        + "projector arch clip · parameters 52.4M · quantization BF16 ·
        175MB" -> 7.2 GB total download;
      * license Apache (2.0).
    The replacement reason: gemma3:27b needed 24 GB+ RAM, beyond most
    classroom/office machines the app targets; the QAT 12B card keeps
    workstation quality at 7.2 GB / ~8 GB RAM.
    """

    def test_qat_card_present(self) -> None:
        names = {m["name"] for m in RECOMMENDED_OLLAMA_MODELS}
        assert "gemma4:12b-it-qat" in names

    def test_gemma3_27b_removed(self) -> None:
        names = {m["name"] for m in RECOMMENDED_OLLAMA_MODELS}
        assert "gemma3:27b" not in names

    def test_qat_card_metadata_matches_verified_facts(self) -> None:
        card = next(
            m for m in RECOMMENDED_OLLAMA_MODELS if m["name"] == "gemma4:12b-it-qat"
        )
        assert card["size"] == "7.2 GB"
        assert card["size_bytes"] == 7_200_000_000
        assert card["task"] == "text"
        assert card["ram"], "RAM hint needed for the Settings card"
        for lang in ("en", "ar", "ur", "hi", "fa"):
            assert lang in card["languages"]
        # Pulling must work natively: explicit quant tags are kept by
        # canonical_model_name (see TestCanonicalName).
        assert canonical_model_name(card["name"]) == "gemma4:12b-it-qat"

    def test_card_urls_are_https_ollama_pages(self) -> None:
        """Every url the catalogue carries must be an https Ollama library
        page (the card links it for manual download)."""
        for m in RECOMMENDED_OLLAMA_MODELS:
            if "url" in m:
                assert m["url"].startswith("https://ollama.com/library/"), m["url"]


class TestCanonicalName:
    def test_explicit_quant_tags_are_kept(self) -> None:
        assert canonical_model_name("gemma4:e4b") == "gemma4:e4b"
        assert canonical_model_name("gemma4:e4b-it-qat") == "gemma4:e4b-it-qat"
        assert canonical_model_name("gemma4:e4b-it-q4_K_M") == "gemma4:e4b-it-q4_K_M"

    def test_implicit_latest_is_stripped(self) -> None:
        assert canonical_model_name("gemma4:latest") == "gemma4"
        assert canonical_model_name("gemma4") == "gemma4"

    def test_model_name_matches_quant_variants(self) -> None:
        assert model_name_matches("gemma4:e4b-it-qat", "gemma4:e4b-it-qat")
        assert model_name_matches("gemma4:e4b", "gemma4")


def _settings_for_ollama() -> Any:
    return get_settings()


def _attach_mock_transport(provider: OllamaProvider, transport: httpx.MockTransport):
    original = provider._client
    provider._client = httpx.AsyncClient(
        base_url=original.base_url,
        headers=original.headers,
        transport=transport,
        timeout=httpx.Timeout(5.0, connect=2.0),
    )
    return original


class TestCapabilityGating:
    @pytest.mark.asyncio
    async def test_supports_tools_accepts_gemma4(self) -> None:
        """Gemma 4 advertises the tools capability on /api/tags — the gate
        must accept it (B3)."""
        provider = OllamaProvider(_settings_for_ollama())
        entry = {"name": "gemma4:e4b", "capabilities": ["completion", "tools", "vision", "thinking"]}

        def handler(req: httpx.Request) -> httpx.Response:
            assert str(req.url).endswith("/api/tags")
            return httpx.Response(200, json={"models": [entry]})

        original = _attach_mock_transport(provider, httpx.MockTransport(handler))
        try:
            assert await provider.supports_tools("gemma4:e4b") is True
        finally:
            await provider._client.aclose()
            provider._client = original

    @pytest.mark.asyncio
    async def test_pick_default_model_prefers_tool_capable_gemma4(self) -> None:
        """With an embedding model installed first, auto-selection must pick
        the tool-capable Gemma 4 (B3/B4: no silent ungrounded default)."""
        provider = OllamaProvider(_settings_for_ollama())
        models = [
            {"name": "nomic-embed-text:latest", "capabilities": ["embedding"]},
            {"name": "gemma4:e4b", "capabilities": ["completion", "tools", "vision"]},
        ]

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"models": models})

        original = _attach_mock_transport(provider, httpx.MockTransport(handler))
        try:
            picked = await provider.pick_default_model()
        finally:
            await provider._client.aclose()
            provider._client = original
        assert picked == "gemma4:e4b"


class TestOllamaTooOld:
    def test_classifier_patterns(self) -> None:
        from api.system import _classify_ollama_error

        assert _classify_ollama_error("model requires a newer version of Ollama") == "ollama_too_old"
        assert _classify_ollama_error("unsupported model architecture") == "ollama_too_old"
        assert _classify_ollama_error("unknown architecture gemma4") == "ollama_too_old"
        assert _classify_ollama_error("pull model manifest: file does not exist") == "model_missing"
        assert _classify_ollama_error("model 'gemma4:e4b' not found, try pulling it first") == "model_missing"
        assert _classify_ollama_error("disk full") == "other"

    def test_humanized_too_old_message_names_the_fix(self) -> None:
        from api.system import _humanize_ollama_error

        msg = _humanize_ollama_error("requires a newer version of Ollama", "0.5.7")
        assert "too old" in msg
        assert "0.5.7" in msg
        assert "ollama.com" in msg
        # Other errors pass through untouched (no fake advice)
        assert _humanize_ollama_error("pull model manifest: file does not exist") == (
            "pull model manifest: file does not exist"
        )

    @pytest.mark.asyncio
    async def test_ollama_version_probe(self) -> None:
        """The /api/version probe returns the installed version (B5 surface)."""
        import api.system as sysmod

        async def patched(url: str) -> str | None:
            def handler(req: httpx.Request) -> httpx.Response:
                assert str(req.url).endswith("/api/version")
                return httpx.Response(200, json={"version": "0.12.10"})

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler), timeout=5.0, trust_env=False, proxy=None
            ) as client:
                r = await client.get(f"{url}/api/version")
                if r.status_code == 200:
                    return str(r.json().get("version"))
            return None

        orig_fn = sysmod._ollama_version
        sysmod._ollama_version = patched  # type: ignore[assignment]
        try:
            got = await patched("http://127.0.0.1:11434")
        finally:
            sysmod._ollama_version = orig_fn  # type: ignore[assignment]
        assert got == "0.12.10"
