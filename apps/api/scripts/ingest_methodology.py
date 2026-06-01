"""apps/api/scripts/ingest_methodology.py — one-shot RAG ingestion.

Reads `prompts/methodology.md`, parses non-mandatory sections into chunks,
embeds each chunk with the configured embedding provider, and inserts them
into the `methodology_chunks` Supabase table.

Usage (from apps/api/ directory):

    python -m scripts.ingest_methodology              # incremental: only inserts if table empty
    python -m scripts.ingest_methodology --reset      # wipe table first

Requires `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `EMBEDDING_API_KEY` in `.env`.
Run the migration SQL in `supabase/migrations/0001_methodology_chunks.sql` first.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow `python -m scripts.ingest_methodology` from apps/api/
API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from rag import chunker, embedder, store  # noqa: E402
from settings import settings  # noqa: E402

log = logging.getLogger("ingest")

METHODOLOGY_PATH = API_ROOT / "prompts" / "methodology.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest methodology.md into pgvector")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe methodology_chunks before inserting",
    )
    parser.add_argument(
        "--methodology",
        type=Path,
        default=METHODOLOGY_PATH,
        help="Path to methodology markdown (default: prompts/methodology.md)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not settings.rag_enabled:
        log.error(
            "RAG is disabled. Need SUPABASE_URL + SUPABASE_SERVICE_KEY + EMBEDDING_API_KEY in .env."
        )
        return 2

    chunks = chunker.load_chunks(args.methodology)
    log.info("parsed %d chunks from %s", len(chunks), args.methodology)
    if not chunks:
        log.error("no chunks produced — check methodology.md heading structure")
        return 1

    existing = store.count()
    log.info("methodology_chunks currently has %d rows", existing)
    if existing and not args.reset:
        log.info("table not empty; pass --reset to re-ingest. Exiting.")
        return 0

    if args.reset and existing:
        deleted = store.delete_all()
        log.info("deleted %d existing rows", deleted)

    log.info("embedding %d chunks via %s ...", len(chunks), settings.EMBEDDING_MODEL)
    vectors = embedder.embed_texts([c.for_embedding() for c in chunks])
    log.info("got %d vectors (dim=%d)", len(vectors), len(vectors[0]) if vectors else 0)

    if vectors and len(vectors[0]) != settings.EMBEDDING_DIMENSIONS:
        log.warning(
            "embedding dim %d does not match EMBEDDING_DIMENSIONS=%d — "
            "make sure the SQL migration's vector(N) matches",
            len(vectors[0]),
            settings.EMBEDDING_DIMENSIONS,
        )

    inserted = store.insert_chunks(chunks, vectors)
    log.info("inserted %d rows", inserted)
    log.info("done. Verify with: select category, section from methodology_chunks order by id;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
