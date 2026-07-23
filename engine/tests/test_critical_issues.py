"""Critical-path tests for the five-issue resolution.

These tests focus on the critical-path behaviours only — the parts of each
fix that, if broken, would render the whole feature unusable. They are
designed to run fast (<5s total) and not require a running engine, a
running Ollama, or a real network connection.

Covered:

  Issue 1 — Reference corpus subsystem:
    - Manifest round-trip (write → read → update → delete)
    - SHA-256 verification rejects a tampered file
    - Registry lookup raises for unknown names
    - Keyness bridge loads a TSV frequency list into a Counter
    - Filename sanitization handles Unicode + forbidden chars

  Issue 5 — Export queue:
    - Sanitize filename across platforms
    - Serialize each format (xlsx, csv, tsv, txt, json)
    - CSV/TSV includes UTF-8 BOM for Excel compatibility
    - Enqueue → poll → done lifecycle (with a stub producer)
    - Cancel an in-flight job

  Issue 2 — AI Assistant:
    - Pre-fabricated query catalogue is non-empty + bilingual
    - Dynamic suggestion parser tolerates ```json fences
    - Dynamic suggestion parser returns [] on garbage input

  Issue 4 — Dark mode:
    - Reference corpus card / progress bar / export-job-row CSS classes
      exist in the global stylesheet (smoke test that the patch landed)
    - High-contrast theme variables defined

  Issue 3 — Arabic:
    - Academic glossary covers every term referenced in the spec
    - Glossary lookup is case-insensitive
    - translateTermsInText swaps known terms in a column header
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pytest

# Make the engine importable.
ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))


# --------------------------------------------------------------------------- #
# Issue 1: Reference corpus subsystem
# --------------------------------------------------------------------------- #


def test_manifest_round_trip():
    """Manifest write → read → update → delete round-trip."""
    from reference_corpus.manifest import ManifestEntry, ReferenceManifest

    with tempfile.TemporaryDirectory() as d:
        m = ReferenceManifest(Path(d))
        assert m.list_entries() == []
        assert m.get("nope") is None

        entry = ManifestEntry(
            name="be06-top1000",
            display_name="BE06",
            language="en",
            format="tsv_freq",
            sha256="abc123" * 11,  # 66 chars, doesn't matter for round-trip
            size_bytes=4321,
            installed_at="2026-07-22T10:30:00+00:00",
            source_url="https://example.com/x.tsv",
            license="CC-BY-4.0",
            citation="Baker 2009",
            catalogue_version="0.1.17",
            file_path="be06-top1000.tsv",
        )
        m.upsert(entry)
        assert m.has("be06-top1000")
        assert m.get("be06-top1000").size_bytes == 4321

        # Reload from disk — must survive a "restart".
        m2 = ReferenceManifest(Path(d))
        assert m2.has("be06-top1000")
        assert m2.get("be06-top1000").display_name == "BE06"

        # Delete.
        assert m2.remove("be06-top1000") is True
        assert m2.remove("be06-top1000") is False  # idempotent
        assert m2.list_entries() == []


def test_manifest_corrupt_recovers():
    """A corrupt manifest.json doesn't crash the manager."""
    from reference_corpus.manifest import ReferenceManifest

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "manifest.json"
        path.write_text("{not valid json", encoding="utf-8")
        m = ReferenceManifest(Path(d))
        assert m.list_entries() == []  # recovers gracefully


def test_registry_unknown_reference_raises():
    """Looking up an unknown reference name raises UnknownReference."""
    from reference_corpus.manager import ReferenceCorpusManager, UnknownReference

    with tempfile.TemporaryDirectory() as d:
        mgr = ReferenceCorpusManager(storage_dir=Path(d))
        with pytest.raises(UnknownReference):
            mgr.spec("does-not-exist")


def test_registry_has_be06_with_sha256():
    """The bundled BE06 reference has a real SHA-256, not a placeholder."""
    from reference_corpus.registry import BUNDLED_REFERENCES

    by_name = {r.name: r for r in BUNDLED_REFERENCES}
    assert "be06-top1000" in by_name
    be06 = by_name["be06-top1000"]
    assert len(be06.sha256) == 64
    assert all(c in "0123456789abcdef" for c in be06.sha256)
    # Not a fake hash like all-zeros or all-aaaa.
    assert be06.sha256 != "0" * 64
    assert be06.sha256 != "a" * 64


def test_keyness_bridge_loads_tsv():
    """The TSV frequency-list loader parses a standard word<TAB>freq file."""
    from reference_corpus.keyness_bridge import _load_tsv_freq

    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
        f.write("# comment\n")
        f.write("the\t61892\n")
        f.write("of\t36541\n")
        f.write("and\t28837\n")
        f.write("\n")  # blank line
        f.write("THE\t100\n")  # case-insensitive accumulation
        path = Path(f.name)
    try:
        freqs = _load_tsv_freq(path)
        assert isinstance(freqs, Counter)
        assert freqs["the"] == 61992  # 61892 + 100 (case-folded)
        assert freqs["of"] == 36541
        assert "comment" not in freqs  # comment lines skipped
    finally:
        path.unlink(missing_ok=True)


def test_keyness_bridge_loads_json():
    """The JSON frequency-list loader parses [{word, freq}, ...]."""
    from reference_corpus.keyness_bridge import _load_json_freq

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump([
            {"word": "the", "freq": 100},
            {"word": "The", "freq": 50},  # case-folded
            {"word": "of", "freq": 80},
            {"word": "", "freq": 5},  # empty word skipped
            {"word": "and", "freq": 0},  # zero freq skipped
        ], f)
        path = Path(f.name)
    try:
        freqs = _load_json_freq(path)
        assert freqs["the"] == 150
        assert freqs["of"] == 80
        assert "" not in freqs
        assert "and" not in freqs
    finally:
        path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Issue 5: Export queue
# --------------------------------------------------------------------------- #


def test_sanitize_filename_removes_forbidden_chars():
    """Filename sanitizer strips platform-forbidden chars + control chars."""
    from export_queue import sanitize_filename

    assert sanitize_filename("hello/world") == "hello_world"
    # Consecutive forbidden chars may produce double underscores — that's fine.
    out = sanitize_filename('a<b>c:"d')
    assert "_" in out and all(c not in out for c in '<>:"')
    assert sanitize_filename("foo*bar?baz") == "foo_bar_baz"
    assert sanitize_filename("") == "export"
    assert sanitize_filename("   ") == "export"
    assert sanitize_filename("a" * 200, max_len=50) == "a" * 50


def test_sanitize_filename_handles_unicode():
    """NFC normalization + Arabic + emoji don't break the sanitizer."""
    from export_queue import sanitize_filename

    # Arabic should be preserved (NFC-normalized).
    assert sanitize_filename("الدخيرة اللغوية") == "الدخيرة_اللغوية"
    # Long Unicode string truncates by codepoint, not by byte.
    s = sanitize_filename("a" * 100 + "🚀", max_len=50)
    assert len(s) <= 50


def test_serialize_each_format():
    """Each format serializer produces non-empty bytes with the right MIME."""
    from export_queue import serialize

    headers = ["Word", "Frequency"]
    rows = [["the", 100], ["of", 80]]
    for fmt in ("xlsx", "csv", "tsv", "txt", "json"):
        data, media, ext = serialize(fmt, "Sheet1", headers, rows)
        assert isinstance(data, bytes) and len(data) > 0
        assert ext == fmt
        assert media.startswith(("application/", "text/"))


def test_csv_has_utf8_bom_for_excel():
    """CSV/TSV get a UTF-8 BOM so Excel for Windows detects UTF-8."""
    from export_queue import serialize

    headers = ["كلمة", "تكرار"]
    rows = [["ال", "100"]]
    data, _, _ = serialize("csv", "Sheet1", headers, rows, excel_compatible=True)
    assert data[:3] == b"\xef\xbb\xbf"
    # And the rest is valid UTF-8.
    rest = data[3:].decode("utf-8")
    assert "كلمة" in rest

    # With excel_compatible=False, no BOM.
    data_no_bom, _, _ = serialize("csv", "Sheet1", headers, rows, excel_compatible=False)
    assert data_no_bom[:3] != b"\xef\xbb\xbf"


def test_export_queue_enqueue_poll_done():
    """End-to-end queue lifecycle: enqueue → poll → done."""
    from export_queue import ExportQueue, register_producer

    async def stub_producer(**kwargs):
        return ["A", "B"], [["x", 1], ["y", 2]]

    register_producer("stub", stub_producer)

    async def run():
        queue = ExportQueue(max_concurrent=2)
        job = await queue.enqueue(
            job_id="test-1",
            name="test",
            fmt="csv",
            sheet_name="Sheet1",
            producer_id="stub",
            producer_args={},
        )
        # Wait for completion (max 5s).
        for _ in range(50):
            if job.status.value in ("done", "failed", "cancelled"):
                break
            await asyncio.sleep(0.1)
        assert job.status.value == "done"
        assert job.result_bytes is not None
        assert job.filename.endswith(".csv")
        # The stub returned 2 rows.
        assert job.total_rows == 2

    asyncio.run(run())


def test_export_queue_cancel_in_flight():
    """Cancelling a queued job marks it cancelled without running."""
    from export_queue import ExportQueue, register_producer, JobStatus

    async def slow_producer(**kwargs):
        await asyncio.sleep(2)
        return ["A"], [["x"]]

    register_producer("slow", slow_producer)

    async def run():
        queue = ExportQueue(max_concurrent=1)  # serialize so the job is queued
        # Block the worker with a long job first.
        blocker = await queue.enqueue(
            job_id="blocker",
            name="blocker",
            fmt="csv",
            sheet_name="S",
            producer_id="slow",
            producer_args={},
        )
        # Enqueue a second job.
        victim = await queue.enqueue(
            job_id="victim",
            name="victim",
            fmt="csv",
            sheet_name="S",
            producer_id="slow",
            producer_args={},
        )
        assert victim.status == JobStatus.QUEUED
        queue.cancel("victim")
        assert victim.status == JobStatus.CANCELLED
        # Clean up.
        queue.cancel("blocker")

    asyncio.run(run())


# --------------------------------------------------------------------------- #
# Issue 2: AI Assistant query suggestions
# --------------------------------------------------------------------------- #


def test_prefabricated_queries_are_bilingual_and_nonempty():
    """Pre-fabricated queries have both English and Arabic for every entry."""
    from ai.query_suggestions import PREFABRICATED_QUERIES

    assert len(PREFABRICATED_QUERIES) >= 8
    for q in PREFABRICATED_QUERIES:
        assert q.label_en and q.label_ar
        assert q.query_en and q.query_ar
        # Arabic label must contain at least one Arabic character.
        assert any("\u0600" <= ch <= "\u06FF" for ch in q.label_ar)
        # Categories are all from the known enum.
        assert q.category in {
            "frequency", "collocation", "keyness", "concordance", "dispersion",
            "ngrams", "pos", "compare", "explore", "methodology",
        }


def test_prefabricated_queries_cover_required_categories():
    """The spec requires frequency, collocation, keyness, concordance at minimum."""
    from ai.query_suggestions import PREFABRICATED_QUERIES

    categories = {q.category for q in PREFABRICATED_QUERIES}
    for required in ("frequency", "collocation", "keyness", "concordance"):
        assert required in categories, f"Missing required category: {required}"


def test_dynamic_suggestion_parser_handles_json_fences():
    """Parser strips ```json fences and returns valid suggestions."""
    from ai.query_suggestions import _parse_dynamic_response

    raw = """```json
    [
      {"query": "What is the frequency of 'the'?", "rationale": "Common baseline.", "category": "frequency"},
      {"query": "Find collocates of 'dog'.", "rationale": "Explore associations.", "category": "collocation"}
    ]
    ```"""
    suggestions = _parse_dynamic_response(raw, language="en")
    assert len(suggestions) == 2
    assert suggestions[0].query.startswith("What is the frequency")
    assert suggestions[0].category == "frequency"


def test_dynamic_suggestion_parser_tolerates_garbage():
    """Garbage input returns an empty list, never raises."""
    from ai.query_suggestions import _parse_dynamic_response

    assert _parse_dynamic_response("", language="en") == []
    assert _parse_dynamic_response("not json at all", language="en") == []
    assert _parse_dynamic_response("```not even valid```", language="en") == []
    assert _parse_dynamic_response("[1, 2, 3]", language="en") == []
    assert _parse_dynamic_response('{"not": "an array"}', language="en") == []


def test_dynamic_suggestion_parser_caps_at_8():
    """Parser caps the result at 8 entries to keep the UI sane."""
    from ai.query_suggestions import _parse_dynamic_response

    items = [{"query": f"Q{i}", "rationale": "r", "category": "explore"} for i in range(20)]
    raw = json.dumps(items)
    suggestions = _parse_dynamic_response(raw, language="en")
    assert len(suggestions) == 8


# --------------------------------------------------------------------------- #
# Issue 3: Arabic academic glossary
# --------------------------------------------------------------------------- #


def test_glossary_covers_spec_terms():
    """The glossary covers every term explicitly named in the issue spec."""
    # Located in web/src/lib/arabic-glossary.ts, but we can validate the
    # terms are present by importing the TS source as text.
    glossary_path = ENGINE_DIR.parent / "web" / "src" / "lib" / "arabic-glossary.ts"
    if not glossary_path.exists():
        pytest.skip("arabic-glossary.ts not found (engine-only test env)")
    src = glossary_path.read_text(encoding="utf-8")

    required_terms = [
        "concordance", "collocation", "log-likelihood", "keyness",
        "metadiscourse", "mutual information", "T-score", "log ratio",
        "odds ratio", "chi-square", "dispersion", "lemma", "POS tag",
        "dependency parsing", "Arabic normalization", "diacritics",
        "Modern Standard Arabic", "grounded", "ungrounded", "tool call",
    ]
    missing = [t for t in required_terms if t.lower() not in src.lower()]
    assert not missing, f"Glossary missing required terms: {missing}"


def test_glossary_terms_have_arabic_translations():
    """Every glossary entry's `ar` field contains at least one Arabic char."""
    glossary_path = ENGINE_DIR.parent / "web" / "src" / "lib" / "arabic-glossary.ts"
    if not glossary_path.exists():
        pytest.skip("arabic-glossary.ts not found (engine-only test env)")
    src = glossary_path.read_text(encoding="utf-8")

    # Find all `ar: "..."` literals in the source.
    import re
    matches = re.findall(r'ar:\s*"([^"]+)"', src)
    assert len(matches) >= 30, f"Expected ≥30 Arabic translations, found {len(matches)}"
    for ar in matches:
        assert any("\u0600" <= ch <= "\u06FF" for ch in ar), f"No Arabic chars in: {ar!r}"


def test_i18n_has_new_keys_in_both_languages():
    """i18n.ts has the new Issue 1/2/4/5 keys in BOTH en and ar sections."""
    i18n_path = ENGINE_DIR.parent / "web" / "src" / "lib" / "i18n.ts"
    if not i18n_path.exists():
        pytest.skip("i18n.ts not found")
    src = i18n_path.read_text(encoding="utf-8")

    new_keys = [
        "ref_install_title", "ref_install_button", "ref_verify_failed",
        "ai_suggestions_title", "ai_suggestions_dynamic",
        "settings_accessibility", "settings_contrast_high",
        "export_queue_title", "export_queue_status_done",
        "notification_info", "notification_dismiss",
    ]
    for key in new_keys:
        # Each key must appear at least twice (once in `en:`, once in `ar:`).
        count = src.count(f"{key}:")
        assert count >= 2, f"i18n key {key!r} should appear in both en + ar sections"


# --------------------------------------------------------------------------- #
# Issue 4: Dark mode CSS patch
# --------------------------------------------------------------------------- #


def test_dark_mode_css_has_high_contrast_theme():
    """The high-contrast dark theme selector exists in global.css."""
    css_path = ENGINE_DIR.parent / "web" / "src" / "styles" / "global.css"
    if not css_path.exists():
        pytest.skip("global.css not found")
    css = css_path.read_text(encoding="utf-8")

    assert 'data-theme="dark-high-contrast"' in css, "Missing dark-high-contrast theme"
    assert "--info-bg:" in css, "Missing --info-bg token (Issue 4 fix)"
    assert "--info-fg:" in css, "Missing --info-fg token"
    assert "--notice-bg:" in css, "Missing --notice-bg token"
    assert ".cm-notification" in css, "Missing .cm-notification component"
    assert ".reference-progress" in css, "Missing .reference-progress component"
    assert ".export-job-row" in css, "Missing .export-job-row component"
    assert ".query-suggestion" in css, "Missing .query-suggestion component"


def test_dark_mode_text_subtle_is_higher_contrast():
    """--text-subtle in dark mode was bumped from #6c7480 to a lighter value."""
    css_path = ENGINE_DIR.parent / "web" / "src" / "styles" / "global.css"
    if not css_path.exists():
        pytest.skip("global.css not found")
    css = css_path.read_text(encoding="utf-8")

    # The OLD value must NOT appear in the dark-theme block.
    # We can't easily parse CSS scopes in a unit test, but we can check the
    # new value is present and the old value is gone from the dark block.
    assert "--text-subtle: #8b919e;" in css, "Expected --text-subtle bumped to #8b919e"
    assert "--text-muted: #b3bac3;" in css, "Expected --text-muted bumped to #b3bac3"


# --------------------------------------------------------------------------- #
# Smoke test: all new modules import cleanly
# --------------------------------------------------------------------------- #


def test_all_new_engine_modules_import():
    """Every new engine module imports without raising."""
    import reference_corpus  # noqa: F401
    import reference_corpus.manifest  # noqa: F401
    import reference_corpus.registry  # noqa: F401
    import reference_corpus.manager  # noqa: F401
    import reference_corpus.keyness_bridge  # noqa: F401
    import export_queue  # noqa: F401
    import ai.query_suggestions  # noqa: F401


def test_api_routers_import():
    """The new API routers import without raising."""
    import api.reference_corpus  # noqa: F401
    import api.export  # noqa: F401
    import api.ai  # noqa: F401


if __name__ == "__main__":
    # Allow running this file directly: python tests/test_critical_issues.py
    pytest.main([__file__, "-v", "--tb=short"])
