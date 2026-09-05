"""Regression tests for the v0.1.25 archive-detection fix in
``api.reference_corpus.download_full_reference``.

Bug being fixed
---------------
BNC Baby and BAWE are hosted on the Oxford Text Archive at URLs that end
with a query string, e.g.::

    https://ota.bodleian.ox.ac.uk/.../2553.zip?sequence=3&isAllowed=y

The old extraction code branch on ``spec.source_url.endswith(".zip")``,
which returns ``False`` for that URL — so the code downloaded the archive
successfully, then silently skipped extraction and reported "No text files
found in archive." for every OTA-hosted corpus.

The fix detects the archive format by **magic bytes** (``b"PK"`` for ZIP,
``b"\\x1f\\x8b"`` for gzip), which works regardless of URL.

These tests run without network access and without spaCy — they patch
``httpx.AsyncClient.get`` to return prebuilt in-memory archives and patch
``ingestion.service.ingest_document`` to a no-op counter, so the full
download → extract → ingest path is exercised end-to-end without any
external dependency.
"""

from __future__ import annotations

import io
import os
import tarfile
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

# --------------------------------------------------------------------------- #
# Test fixture: fresh in-memory app
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client():
    """Spawn the FastAPI app with a fresh in-memory DB per test."""
    os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-archive-data"

    from app.settings import get_settings

    get_settings.cache_clear()
    from storage.session import _engine, dispose_db

    _engine.clear() if hasattr(_engine, "clear") else None

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
    await dispose_db()


async def _wait_for_job(client, name: str, *, timeout_s: float = 5.0) -> dict:
    """Poll the download-full status endpoint until terminal state."""
    import asyncio

    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/v1/reference-corpora/{name}/download-full/status")
        assert r.status_code == 200, r.text
        job = r.json()
        if job.get("status") in ("installed", "failed"):
            return job
        await asyncio.sleep(0.05)
    pytest.fail(f"Job for {name} did not reach terminal state within {timeout_s}s")


class _FakeStreamResponse:
    """Minimal stand-in for an httpx streaming response — only the
    attributes the v1.2.0 download pipeline touches."""

    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.headers = {"content-length": str(len(content))}

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self):
        yield self.content


class _FakeStreamContext:
    """Async context manager returned by the fake ``client.stream()``."""

    def __init__(self, response: _FakeStreamResponse):
        self._response = response

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._response

    async def __aexit__(self, *args) -> bool:
        return False


def _make_fake_client(route):
    """Build a fake httpx.AsyncClient class whose ``stream()`` calls
    ``route(url)`` to decide the outcome:

      * ``bytes``              → 200 streaming response with those bytes
      * ``int``                → streaming response with that HTTP status
      * ``Exception`` instance → raised synchronously by ``stream()``
      * ``None``               → 200 with an empty body

    ``route`` is consulted once per (url, attempt) so tests can model
    retries (e.g. pop from a list of outcomes).
    """

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, **kwargs):
            outcome = route(url)
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, int):
                return _FakeStreamContext(_FakeStreamResponse(b"", status_code=outcome))
            return _FakeStreamContext(_FakeStreamResponse(outcome or b""))

    return _FakeAsyncClient


def _build_zip_archive(files: dict[str, str]) -> bytes:
    """Build an in-memory ZIP. ``files`` maps archive path → file content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _build_targz_archive(files: dict[str, str]) -> bytes:
    """Build an in-memory tar.gz. ``files`` maps archive path → file content."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _patch_download(monkeypatch, archive_bytes: bytes) -> list[str]:
    """Patch httpx + ingest_document so the background download task runs
    without network and without spaCy. Returns the list of ingested filenames
    so individual tests can assert on it."""
    import httpx

    seen_urls: list[str] = []

    def _route(url: str):
        seen_urls.append(url)
        return archive_bytes

    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_route))

    import ingestion.service as ingest_mod

    ingested_files: list[str] = []

    async def _fake_ingest(session, corpus, filename, raw, *, metadata=None, language=None):
        ingested_files.append(filename)
        return None

    monkeypatch.setattr(ingest_mod, "ingest_document", _fake_ingest)
    # The endpoint imports ingest_document at module level, so patch the
    # symbol the endpoint module looks up too.
    import api.reference_corpus as api_ref

    monkeypatch.setattr(api_ref, "ingest_document", _fake_ingest, raising=False)
    return ingested_files


# --------------------------------------------------------------------------- #
# Test 1 — Pure unit test: the bug exists with the OLD logic, the fix works
# --------------------------------------------------------------------------- #


def test_old_url_suffix_check_fails_on_ota_query_string():
    """Prove the bug: ``url.endswith('.zip')`` returns False for the real
    BNC Baby URL, so the OLD extraction code would have skipped it."""
    bnc_baby_url = (
        "https://ota.bodleian.ox.ac.uk/repository/xmlui/bitstream/"
        "handle/20.500.12024/2553/2553.zip?sequence=3&isAllowed=y"
    )
    # Old logic (the bug):
    assert not bnc_baby_url.endswith(".zip"), (
        "If this assertion fails, the URL has changed and the bug may no "
        "longer reproduce — revisit the fix."
    )
    assert not bnc_baby_url.endswith(".tar.gz") and not bnc_baby_url.endswith(".tgz")

    # New logic (the fix): magic-byte sniffing works regardless of URL.
    zip_bytes = _build_zip_archive({"Texts/Aca/sample.txt": "hello world"})
    assert zip_bytes[:2] == b"PK", "ZIP magic bytes must be b'PK'"

    gzip_bytes = _build_targz_archive({"eng_news_2023_10K-sentences.txt": "1\tHello.\n2\tWorld.\n"})
    assert gzip_bytes[:2] == b"\x1f\x8b", "gzip magic bytes must be b'\\x1f\\x8b'"


# --------------------------------------------------------------------------- #
# Test 2 — ZIP at a query-string URL is detected + extracted (the BNC Baby case)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_zip_with_query_string_url_is_extracted(client, monkeypatch):
    """End-to-end: a ZIP served at an OTA-style URL (ending in
    ``isAllowed=y``) is detected via magic bytes, extracted, and ingested.

    This is the canonical reproduction of the bug — without the fix, the
    background task would set status=failed with the message
    "No text files found in archive."
    """
    # Build a ZIP that mimics BNC Baby's structure: Texts/<Genre>/<file>.txt
    zip_bytes = _build_zip_archive(
        {
            "Texts/Aca/AA.txt": "Academic writing sample one. Another sentence here.",
            "Texts/Fic/FN.txt": "Once upon a time, in a galaxy far far away.",
            "Texts/News/ABC.txt": "LONDON — The government announced new policy today.",
            "Texts/Dem/KS.txt": "Right so I was walking down the pub the other day.",
        }
    )

    ingested_files = _patch_download(monkeypatch, zip_bytes)

    # Trigger the download. The endpoint returns immediately.
    r = await client.post("/api/v1/reference-corpora/bnc-baby/download-full")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "started"

    job = await _wait_for_job(client, "bnc-baby")
    assert job["status"] == "installed", (
        f"Expected installed, got: {job!r}. Without the fix this would be "
        "'failed' with message 'No text files found in archive.'"
    )
    assert job["document_count"] == 4, f"Expected 4 docs ingested, got {job['document_count']}"
    assert len(ingested_files) == 4


# --------------------------------------------------------------------------- #
# Test 2b — BAWE: same OTA URL pattern, different corpus entry
# --------------------------------------------------------------------------- #
#
# BAWE shares the *exact* same bug shape as BNC Baby (Oxford Text Archive
# URL ending in ``isAllowed=y``), but exercises a different registry entry
# with a different ``source_url`` (``2539.zip`` vs ``2553.zip``), a
# different ``display_name``, and a different default ``genre`` ("academic"
# vs "mixed"). Belts-and-braces: this confirms the fix is not somehow
# specific to the BNC Baby entry.


@pytest.mark.asyncio
async def test_bawe_zip_with_query_string_url_is_extracted(client, monkeypatch):
    """End-to-end BAWE reproduction: same OTA URL shape as BNC Baby but a
    distinct registry entry (``2539.zip``, genre="academic"). Without the
    fix, BAWE would fail with the same "No text files found in archive."
    message because its URL also ends in ``isAllowed=y``."""
    # Confirm the BAWE registry entry actually has the bug shape — if this
    # URL ever changes to end in ".zip" literally, the test would still
    # pass but would no longer be exercising the bug. Guard against that.
    from reference_corpus.registry import BUNDLED_REFERENCES

    bawe_spec = next((s for s in BUNDLED_REFERENCES if s.name == "bawe"), None)
    assert bawe_spec is not None, "BAWE entry missing from BUNDLED_REFERENCES"
    assert "2539.zip" in bawe_spec.source_url, (
        f"BAWE URL changed unexpectedly: {bawe_spec.source_url!r}"
    )
    assert not bawe_spec.source_url.endswith(".zip"), (
        "BAWE URL now ends in '.zip' literally — this test no longer "
        "reproduces the bug; please revisit."
    )
    assert bawe_spec.source_url.endswith("isAllowed=y"), (
        f"BAWE URL no longer ends in 'isAllowed=y': {bawe_spec.source_url!r}"
    )
    # v1.2.0: BAWE must declare a mirror list whose LAST entry is the
    # canonical OTA URL and which includes a project-hosted mirror.
    assert bawe_spec.source_urls, "BAWE must list source_urls (mirror fallback)"
    assert bawe_spec.source_urls[-1] == bawe_spec.source_url, (
        "The canonical OTA URL must be the LAST entry in source_urls"
    )
    assert any(
        "github.com/waleedmandour/CorpusMind/releases" in u for u in bawe_spec.source_urls
    ), f"BAWE must list a project-hosted mirror: {bawe_spec.source_urls!r}"

    # BAWE is organized by discipline + level. Build a ZIP with a small
    # representative subset mirroring that structure.
    zip_bytes = _build_zip_archive(
        {
            "BAWE/A/Arts/Level1/0113a.txt": (
                "This essay examines the representation of women in Victorian novels."
            ),
            "BAWE/A/SocialSciences/Level2/0214b.txt": (
                "The demographic transition model describes four stages of population change."
            ),
            "BAWE/A/PhysicalSciences/Level3/0315c.txt": (
                "The Michaelis-Menten equation describes enzyme kinetics."
            ),
            "BAWE/A/LifeSciences/Level4/0416d.txt": (
                "Photosynthesis converts light energy into chemical energy stored in glucose."
            ),
        }
    )

    ingested_files = _patch_download(monkeypatch, zip_bytes)

    r = await client.post("/api/v1/reference-corpora/bawe/download-full")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "started"

    job = await _wait_for_job(client, "bawe")
    assert job["status"] == "installed", (
        f"Expected installed, got: {job!r}. Without the fix this would be "
        "'failed' with message 'No text files found in archive.'"
    )
    assert job["document_count"] == 4, f"Expected 4 docs ingested, got {job['document_count']}"
    assert len(ingested_files) == 4


# --------------------------------------------------------------------------- #
# Test 3 — tar.gz (Leipzig) path still works (no regression)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_targz_leipzig_path_still_works(client, monkeypatch):
    """Regression guard: the tar.gz branch (used by Leipzig 10K corpora)
    must continue to work after the magic-byte refactor."""
    # Leipzig sentence files are TSV: id<TAB>sentence
    targz_bytes = _build_targz_archive(
        {
            "eng_news_2023_10K-sentences.txt": (
                "1\tThe prime minister held a press conference today.\n"
                "2\tScientists discovered a new species in the Amazon.\n"
                "3\tThe stock market closed higher on Friday.\n"
            ),
        }
    )

    _patch_download(monkeypatch, targz_bytes)

    r = await client.post("/api/v1/reference-corpora/leipzig-english-news-10k/download-full")
    assert r.status_code == 200, r.text

    job = await _wait_for_job(client, "leipzig-english-news-10k")
    assert job["status"] == "installed", f"Expected installed, got: {job!r}"
    # 3 sentences → 3 documents
    assert job["document_count"] == 3, f"Expected 3 docs, got {job['document_count']}"


# --------------------------------------------------------------------------- #
# Test 4 — Unrecognized format produces the new clearer error
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_unrecognized_format_produces_clear_error(client, monkeypatch):
    """If the downloaded bytes are neither ZIP nor tar.gz, the user gets a
    useful error naming the expected magic bytes — NOT the misleading
    'No text files found in archive.'"""
    garbage = b"<!DOCTYPE html><html>this is not an archive</html>"

    # NOTE: no ingest stub needed — the task fails before ingestion runs.
    import httpx

    def _route(url: str):
        return garbage

    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_route))

    r = await client.post("/api/v1/reference-corpora/bnc-baby/download-full")
    assert r.status_code == 200, r.text

    job = await _wait_for_job(client, "bnc-baby")
    assert job["status"] == "failed", f"Expected failed, got: {job!r}"
    msg = job["message"]
    # Must mention magic bytes (the new clearer message) — NOT the old one.
    assert "magic bytes" in msg, f"Expected clearer error, got: {msg!r}"
    assert "No text files found in archive." not in msg, (
        f"Old misleading error surfaced — got: {msg!r}"
    )


# --------------------------------------------------------------------------- #
# Test 5 — Background task is held by a strong reference (Fix #12)
# --------------------------------------------------------------------------- #


def test_background_task_set_exists():
    """Fix #12: the module exposes a strong-reference set for background
    tasks so asyncio cannot GC them mid-download."""
    import api.reference_corpus as api_ref

    assert hasattr(api_ref, "_full_corpus_tasks"), (
        "_full_corpus_tasks set must exist to hold strong refs to background "
        "download tasks (Fix #12)."
    )
    assert isinstance(api_ref._full_corpus_tasks, set)


# --------------------------------------------------------------------------- #
# Test 6 — Multiple .xml files in the same directory all extract (Fix #13)
# --------------------------------------------------------------------------- #


def _bnc_xml(word1: str, word2: str) -> str:
    """A minimal but structurally real BNC/TEI-XML document: <w> nested in
    <s> nested in <body> nested in <text>, matching the actual shape that
    triggered both this bug and the earlier word-duplication bug."""
    return (
        f"<text><body><div1><p>"
        f'<s n="1"><w c5="AT0">{word1} </w><w c5="NN1">{word2}</w>'
        f'<c c5="PUN">.</c></s>'
        f"</p></div1></body></text>"
    )


@pytest.mark.asyncio
async def test_multiple_xml_files_in_same_directory_all_extract(client, monkeypatch):
    """Reproduces Fix #13: a genre folder with 3 .xml files must extract
    all 3, not crash on the 2nd file with a root-variable TypeError."""
    zip_bytes = _build_zip_archive(
        {
            "Texts/Aca/AA0.xml": _bnc_xml("First", "document"),
            "Texts/Aca/AA1.xml": _bnc_xml("Second", "document"),
            "Texts/Aca/AA2.xml": _bnc_xml("Third", "document"),
        }
    )

    ingested_files = _patch_download(monkeypatch, zip_bytes)

    r = await client.post("/api/v1/reference-corpora/bnc-baby/download-full")
    assert r.status_code == 200, r.text

    job = await _wait_for_job(client, "bnc-baby")
    assert job["status"] == "installed", (
        f"Expected installed, got: {job!r}. Without the fix this fails on "
        f"the 2nd .xml file in the directory with "
        f'"TypeError: expected str, bytes or os.PathLike object, not '
        f'BeautifulSoup" (or "not Tag").'
    )
    assert job["document_count"] == 3, f"Expected 3 docs, got {job['document_count']}"
    assert len(ingested_files) == 3


# --------------------------------------------------------------------------- #
# v1.2.0 tests — robust download pipeline (retries, mirrors, offline import)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_download_retries_on_504_then_succeeds(client, monkeypatch):
    """A transient 504 from the source gateway must NOT fail the job: the
    pipeline retries the same URL (with backoff) before moving on."""
    import api.reference_corpus as api_ref

    monkeypatch.setattr(api_ref, "DOWNLOAD_RETRY_BACKOFF_S", (0.01, 0.01))

    zip_bytes = _build_zip_archive({"Texts/Aca/AA0.xml": _bnc_xml("Retry", "success")})
    ingested_files = _patch_download(monkeypatch, zip_bytes)

    outcomes = [504, zip_bytes]  # first attempt 504 → second succeeds
    import httpx

    def _route(url: str):
        return outcomes.pop(0)

    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_route))

    r = await client.post("/api/v1/reference-corpora/bnc-baby/download-full")
    assert r.status_code == 200, r.text

    job = await _wait_for_job(client, "bnc-baby")
    assert job["status"] == "installed", (
        f"A single transient 504 should be retried, not fatal: {job!r}"
    )
    assert job["document_count"] == 1
    assert len(ingested_files) == 1


@pytest.mark.asyncio
async def test_download_falls_back_between_mirror_and_canonical(client, monkeypatch):
    """v1.2.0 mirror fallback, OTA direction: the project-hosted mirror is
    tried FIRST; when it fails, the pipeline falls back to the canonical
    OTA URL and still installs."""
    import httpx

    import api.reference_corpus as api_ref

    monkeypatch.setattr(api_ref, "DOWNLOAD_RETRY_BACKOFF_S", (0.01, 0.01))

    zip_bytes = _build_zip_archive(
        {
            "BAWE/A/Arts/Level1/0113a.txt": "Mirror fallback document text.",
        }
    )
    _patch_download(monkeypatch, zip_bytes)

    seen_urls: list[str] = []

    def _route(url: str):
        seen_urls.append(url)
        if "github.com/waleedmandour/CorpusMind/releases" in url:
            return 404  # mirror asset missing → fall through
        return zip_bytes  # canonical OTA URL serves the archive

    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_route))

    r = await client.post("/api/v1/reference-corpora/bawe/download-full")
    assert r.status_code == 200, r.text

    job = await _wait_for_job(client, "bawe")
    assert job["status"] == "installed", f"Mirror→OTA fallback failed: {job!r}"
    assert job["document_count"] == 1
    # The mirror must have been attempted before the OTA URL.
    assert "github.com/waleedmandour/CorpusMind/releases" in seen_urls[0], (
        f"Mirror should be tried first, saw: {seen_urls!r}"
    )
    assert any("ota.bodleian" in u for u in seen_urls)


@pytest.mark.asyncio
async def test_all_sources_fail_gives_actionable_message(client, monkeypatch):
    """When every source fails, the job message must tell the user about
    the offline 'Import archive' path instead of surfacing a raw httpx
    error string."""
    import httpx

    import api.reference_corpus as api_ref

    monkeypatch.setattr(api_ref, "DOWNLOAD_RETRY_BACKOFF_S", (0.01, 0.01))

    _patch_download(monkeypatch, b"unused")

    def _route(url: str):
        return 504

    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_route))

    r = await client.post("/api/v1/reference-corpora/bnc-baby/download-full")
    assert r.status_code == 200, r.text

    job = await _wait_for_job(client, "bnc-baby", timeout_s=10)
    assert job["status"] == "failed", f"Expected failed, got: {job!r}"
    msg = job["message"]
    assert "All download sources failed" in msg
    assert "Import archive" in msg, f"Failure must point to the offline import path: {msg!r}"
    # No raw httpx exception text may leak as the WHOLE message.
    assert not msg.startswith("Server error"), msg


@pytest.mark.asyncio
async def test_import_archive_endpoint_installs_corpus(client, monkeypatch):
    """Offline import: uploading a manually downloaded ZIP installs the
    corpus through the same extract→ingest pipeline as download-full."""
    zip_bytes = _build_zip_archive(
        {
            "BAWE/A/Arts/Level1/0113a.txt": "Imported document text.",
        }
    )
    ingested_files = _patch_download(monkeypatch, zip_bytes)

    r = await client.post(
        "/api/v1/reference-corpora/bawe/import-archive",
        files={"file": ("2539.zip", zip_bytes, "application/zip")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "started", body

    job = await _wait_for_job(client, "bawe")
    assert job["status"] == "installed", f"Import failed: {job!r}"
    assert job["document_count"] == 1
    assert len(ingested_files) == 1


@pytest.mark.asyncio
async def test_import_archive_rejects_non_archive(client):
    """Uploading a non-archive file must fail fast with a clear magic-bytes
    error — not extract garbage or fail obscurely later."""
    r = await client.post(
        "/api/v1/reference-corpora/bawe/import-archive",
        files={"file": ("page.html", b"<html>not an archive</html>", "text/html")},
    )
    assert r.status_code == 400, r.text
    assert "magic bytes" in r.json()["detail"], r.text


@pytest.mark.asyncio
async def test_max_files_cap_is_a_registry_field(client, monkeypatch):
    """v1.2.0: the ingestion cap moved from a hardcoded 500 to the registry
    field ``ReferenceCorpusSpec.max_files`` — the endpoint must honor it."""
    import dataclasses

    import api.reference_corpus as api_ref
    from reference_corpus.registry import BUNDLED_REFERENCES

    files = {f"doc{i}.txt": f"Document number {i} body text." for i in range(6)}
    zip_bytes = _build_zip_archive(files)
    _patch_download(monkeypatch, zip_bytes)

    bawe_spec = next(s for s in BUNDLED_REFERENCES if s.name == "bawe")
    capped = dataclasses.replace(bawe_spec, max_files=2)

    class _StubMgr:
        def spec(self, name):
            return capped

    monkeypatch.setattr(api_ref, "get_manager", lambda: _StubMgr())

    r = await client.post("/api/v1/reference-corpora/bawe/download-full")
    assert r.status_code == 200, r.text

    job = await _wait_for_job(client, "bawe")
    assert job["status"] == "installed", f"{job!r}"
    assert job["document_count"] == 2, f"max_files=2 cap ignored, ingested {job['document_count']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
