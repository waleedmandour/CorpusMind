"""F4: deterministic local reproduction of the KWIC limit-1000 failure.

The engine's word-level concordance context fetch (engine/stats/service.py,
~line 498-516) builds ONE un-chunked or_() over every distinct matched
(doc_id, sentence_idx) pair; the phrase path chunks at 400 but the word path
does not. With limit=1000 and >= ~950 distinct matched sentences the or_()/
and_() expression tree exceeds SQLite's maximum expression depth (1000) and
SQLite raises "Expression tree is too large (maximum depth 1000)".

This script ingests a small corpus (1 doc, 1200 one-'the' sentences) and runs
the production search_concordance at limit=400 (expected OK) and limit=1000
(expected depth failure). Exit code 0 + printed evidence = reproduced.
"""
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1] / "engine"
sys.path.insert(0, str(REPO))
os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:////tmp/kwic_repro/kwic.db"
os.environ["CORPUSMIND_ARABIC_WARMUP"] = "0"
Path("/tmp/kwic_repro").mkdir(exist_ok=True)
for p in Path("/tmp/kwic_repro").glob("kwic.db*"):
    p.unlink()


async def main() -> None:
    from app.settings import get_settings
    get_settings.cache_clear()
    from storage.models import Corpus, Project
    from storage.session import init_db, dispose_db, get_session
    from ingestion.service import ingest_document
    from stats.service import search_concordance

    await init_db()
    async for session in get_session():
        project = Project(name="kwic-repro")
        session.add(project)
        await session.flush()
        corpus = Corpus(project_id=project.id, name="repro", language="en")
        session.add_all([corpus])
        await session.flush()
        # 1200 sentences, exactly one 'the' each -> 1200 distinct sentences
        text = " ".join(f"the word{i} follows here." for i in range(1200))
        await ingest_document(session, corpus, "repro.txt", text.encode(),
                              language="en")
        await session.commit()

        for lim in (400, 1000):
            try:
                r = await search_concordance(session, corpus.id, "the",
                                             level="word", window=5, limit=lim)
                print(f"limit={lim}: OK, total={r.total} lines returned={len(r.lines)}")
            except Exception as e:
                print(f"limit={lim}: {type(e).__name__}: {str(e)[:160]}")
    await dispose_db()


asyncio.run(main())
