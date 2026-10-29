"""Language capability registry endpoint + Student Mode allowlist (v1.2.11).

A1: GET /api/v1/languages is the machine-readable single source of truth;
A8: the endpoint is consciously placed on the student route allowlist
(read-only metadata the classroom UI needs), while every management route
stays teacher-only. The student-denial tests here pin the boundary.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"

    from app.main import app
    from storage.session import dispose_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


class TestLanguagesEndpoint:
    @pytest.mark.asyncio
    async def test_registry_lists_five_languages(self, client: AsyncClient) -> None:
        r = await client.get("/api/v1/languages")
        assert r.status_code == 200
        d = r.json()
        codes = [l["code"] for l in d["languages"]]
        assert codes == ["en", "ar", "ur", "hi", "fa"]

    @pytest.mark.asyncio
    async def test_script_direction_metadata(self, client: AsyncClient) -> None:
        d = (await client.get("/api/v1/languages")).json()
        by = {l["code"]: l for l in d["languages"]}
        assert by["ur"]["direction"] == "rtl" and by["ur"]["script"] == "Perso-Arabic"
        assert by["fa"]["direction"] == "rtl"
        assert by["hi"]["direction"] == "ltr" and by["hi"]["script"] == "Devanagari"
        assert by["ar"]["direction"] == "rtl" and by["en"]["direction"] == "ltr"

    @pytest.mark.asyncio
    async def test_tool_matrix_honesty(self, client: AsyncClient) -> None:
        """Tools ur/hi/fa do not support must SAY so — the registry is the
        source the UI renders, so its honesty is contractual."""
        d = (await client.get("/api/v1/languages")).json()
        by = {l["code"]: l for l in d["languages"]}
        for code in ("ur", "hi", "fa"):
            tools = by[code]["tools"]
            assert tools["concordance"]["support"] == "supported"
            assert tools["frequency"]["support"] == "supported"
            assert tools["sentiment"]["support"] == "unavailable"
            assert tools["learner_errors"]["support"] == "unavailable"
            assert tools["vocab_profile"]["support"] == "unavailable"
            assert tools["arabic_morphology"]["support"] == "unavailable"
        # Arabic keeps its morphology tooling; vocab bands stay en-only
        assert by["ar"]["tools"]["arabic_morphology"]["support"] == "supported"
        assert by["ar"]["tools"]["vocab_profile"]["support"] == "unavailable"
        assert by["en"]["tools"]["vocab_profile"]["support"] == "supported"

    @pytest.mark.asyncio
    async def test_coverage_labels_present(self, client: AsyncClient) -> None:
        d = (await client.get("/api/v1/languages")).json()
        for l in d["languages"]:
            assert l["coverage_label"]
            assert l["stopword_count"] >= 0


class TestStudentAllowlist:
    """A8: the student role must reach the new read-only registry but never
    the management routes (pull/delete models, settings, server-mode)."""

    def test_languages_route_is_on_allowlist(self) -> None:
        from app.server_mode import student_route_allowed

        assert student_route_allowed("GET", "/api/v1/languages")

    def test_management_routes_stay_off_allowlist(self) -> None:
        from app.server_mode import student_route_allowed

        # Model management (Gemma 4 pull/delete surface)
        assert not student_route_allowed("POST", "/api/v1/ollama/pull")
        assert not student_route_allowed("GET", "/api/v1/ollama/catalogue")
        assert not student_route_allowed("DELETE", "/api/v1/ollama/models")
        # Engine settings + server-mode admin
        assert not student_route_allowed("GET", "/api/v1/settings")
        assert not student_route_allowed("POST", "/api/v1/server-mode/config")
        assert not student_route_allowed("GET", "/api/v1/server-mode/capacity")
        # Corpus mutation
        assert not student_route_allowed("POST", "/api/v1/projects")
        assert not student_route_allowed("DELETE", "/api/v1/corpora/x/documents/y")
        # The languages metadata must not leak mutation powers
        assert not student_route_allowed("POST", "/api/v1/languages")
        assert not student_route_allowed("DELETE", "/api/v1/languages")
