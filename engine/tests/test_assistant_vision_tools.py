"""v1.2.0 Lens round — assistant vision/cross-modal tools.

These tests call execute_tool() directly (no LLM involved): the tools
read cached analysis from the DB, so the assistant can ground answers
about images without calling a vision model at answer time.

Uses a file-based SQLite DB (execute_tool opens its own session_scope).
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

_DB_FILE = "/tmp/cm-test-assistant-vision.db"
if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)
os.environ["CORPUSMIND_DB_URL"] = f"sqlite+aiosqlite:///{_DB_FILE}"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-assistantvision"

import pytest  # noqa: E402 — env must be set first

from ai.tools import execute_tool, schemas_for_llm  # noqa: E402
from storage.session import dispose_db, init_db, session_scope  # noqa: E402


@pytest.fixture(autouse=True)
async def _db():
    if os.path.exists(_DB_FILE):
        os.remove(_DB_FILE)
    await init_db()
    yield
    await dispose_db()


async def _seed():
    """Insert project + corpus + document + annotation version + image set
    with two analysed images (cached OCR + VLM + discourse caches)."""
    from storage.models import (
        AnnotationVersion,
        Corpus,
        Document,
        Image,
        ImageSet,
        Project,
    )

    async with session_scope() as s:
        pid = uuid.uuid4().hex[:16]
        cid = uuid.uuid4().hex[:16]
        s.add(Project(id=pid, name="P", language="en"))
        s.add(Corpus(id=cid, project_id=pid, name="Cross-modal corpus", language="en"))
        s.add(Document(id=uuid.uuid4().hex[:16], corpus_id=cid, filename="doc1.txt"))
        s.add(AnnotationVersion(
            id=uuid.uuid4().hex[:16], corpus_id=cid,
            token_count=1234, type_count=321, sentence_count=45,
        ))
        sid = uuid.uuid4().hex[:16]
        s.add(ImageSet(id=sid, corpus_id=cid, name="Front pages"))
        for i in range(2):
            s.add(Image(
                id=uuid.uuid4().hex[:16],
                image_set_id=sid,
                filename=f"front{i}.png",
                analysis={
                    "ocr": {"text": f"Breaking news headline {i}", "confidence": 0.9,
                            "word_count": 4, "engine": "tesseract", "language": "eng"},
                    "colours": {}, "composition": {},
                    "vision_llm": {
                        "default:abc": {"description": f"Image {i} shows a protest crowd.",
                                        "model": "qwen3-vl:2b", "provider": "ollama",
                                        "prompt": "Describe this image.",
                                        "prompt_hash": "abc",
                                        "timestamp": datetime.now(UTC).isoformat()},
                    },
                    "vision_llm_discourse": {
                        "social_semiotic:qwen3-vl:2b:def": {
                            "claims": [
                                {"framework": "Social semiotics", "category": "salience",
                                 "claim": "hypothesis A", "evidence": [], "confidence": 0.5},
                                {"framework": "Social semiotics", "category": "salience",
                                 "claim": "hypothesis B", "evidence": [], "confidence": 0.4},
                            ],
                            "provenance": {"timestamp": "2026-01-01T00:00:00Z"},
                        },
                    },
                },
            ))
    return cid, sid


@pytest.mark.asyncio
async def test_list_image_sets_counts():
    cid, _ = await _seed()
    r = await execute_tool("list_image_sets", {"corpus_id": cid})
    assert r["image_set_count"] == 1
    assert r["image_sets"][0]["image_count"] == 2
    assert r["corpus_name"] == "Cross-modal corpus"


@pytest.mark.asyncio
async def test_get_image_set_summary_aggregates_cache():
    _cid, sid = await _seed()
    r = await execute_tool("get_image_set_summary", {"image_set_id": sid})
    assert r["image_count"] == 2
    assert r["images_with_vlm"] == 2
    assert r["images_with_discourse"] == 2
    assert r["recurring_themes"][0]["framework"] == "social_semiotic"
    salience = next(c for c in r["recurring_themes"][0]["categories"] if c["category"] == "salience")
    assert salience["count"] == 4  # 2 claims × 2 images
    words = {w["word"] for w in r["top_ocr_words"]}
    assert {"breaking", "news", "headline"} <= words
    assert len(r["description_samples"]) == 2
    assert r["note"] == ""


@pytest.mark.asyncio
async def test_get_corpus_overview_cross_modal():
    cid, _sid = await _seed()
    r = await execute_tool("get_corpus_overview", {"corpus_id": cid})
    assert r["text_side"]["document_count"] == 1
    assert r["text_side"]["token_count"] == 1234
    assert r["vision_side"]["image_set_count"] == 1
    assert r["vision_side"]["image_count"] == 2
    # Both sides populated → cross-modal hint fires.
    assert "BOTH" in r["note"]


@pytest.mark.asyncio
async def test_unknown_ids_return_error_dicts():
    await _seed()
    r = await execute_tool("list_image_sets", {"corpus_id": "missing"})
    assert "error" in r
    r = await execute_tool("get_image_set_summary", {"image_set_id": "missing"})
    assert "error" in r
    r = await execute_tool("get_corpus_overview", {"corpus_id": "missing"})
    assert "error" in r


def test_new_tools_in_schema_and_registry():
    schemas = {s["function"]["name"]: s["function"] for s in schemas_for_llm()}
    for name in ("list_image_sets", "get_image_set_summary", "get_corpus_overview"):
        assert name in schemas, name
    assert "corpus_id" in schemas["get_corpus_overview"]["parameters"]["required"]
    assert "image_set_id" in schemas["get_image_set_summary"]["parameters"]["required"]
