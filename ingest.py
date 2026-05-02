"""
Ingestion pipeline — run this once to populate Supabase.

Usage:
    python ingest.py
    python ingest.py --dry-run          # parse + chunk only, no DB writes
    python ingest.py --topic xss        # ingest only chunks for one topic
    python ingest.py --resume           # skip chunk_ids already in Supabase
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from tqdm import tqdm

from chunker import Chunk, sections_to_chunks
from config import settings
from db import SupabaseDB
from embedder import GeminiEmbedder
from pdf_extractor import extract_sections


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest PDF into Supabase vector store")
    p.add_argument("--dry-run",  action="store_true", help="Parse and chunk without writing to DB")
    p.add_argument("--topic",    default=None,         help="Restrict to a single topic slug")
    p.add_argument("--resume",   action="store_true", help="Skip chunk_ids already stored in Supabase")
    p.add_argument("--batch",    type=int, default=settings.embed_batch_size, help="Embedding batch size")
    return p.parse_args()


def _get_existing_ids(db: SupabaseDB) -> set[str]:
    """Fetch all chunk_ids currently stored (for --resume)."""
    resp = db.client.table("cyber_chunks").select("chunk_id").execute()
    return {row["chunk_id"] for row in (resp.data or [])}


def run(
    dry_run: bool = False,
    topic_filter: Optional[str] = None,
    resume: bool = False,
    batch_size: int = 20,
) -> None:
    pdf = settings.pdf_path_resolved
    print(f"[ingest] PDF : {pdf}")
    print(f"[ingest] Extracting sections …")

    sections = extract_sections(pdf)
    print(f"[ingest] Sections extracted : {len(sections)}")

    chunks = sections_to_chunks(
        sections,
        max_words=settings.chunk_max_words,
        min_words=settings.chunk_min_words,
    )
    print(f"[ingest] Chunks produced    : {len(chunks)}")

    if topic_filter:
        chunks = [c for c in chunks if c.topic == topic_filter]
        print(f"[ingest] After topic filter  : {len(chunks)} (topic={topic_filter})")

    if not chunks:
        print("[ingest] Nothing to ingest — check topic signals in chunker.py")
        return

    # Print topic distribution
    from collections import Counter
    dist = Counter(c.topic for c in chunks)
    print("[ingest] Topic distribution:")
    for t, n in dist.most_common():
        print(f"         {t:<30} {n}")

    if dry_run:
        print("[ingest] --dry-run: stopping before DB writes.")
        return

    db       = SupabaseDB(settings.supabase_url, settings.supabase_service_key)
    embedder = GeminiEmbedder(settings.gemini_api_key)

    if resume:
        existing = _get_existing_ids(db)
        before = len(chunks)
        chunks = [c for c in chunks if c.chunk_id not in existing]
        print(f"[ingest] --resume: skipped {before - len(chunks)} existing chunks, {len(chunks)} remaining")

    if not chunks:
        print("[ingest] All chunks already stored.")
        return

    import time
    # Embed + store in batches
    stored = 0
    for i in tqdm(range(0, len(chunks), batch_size), desc="Embedding batches"):
        batch: list[Chunk] = chunks[i : i + batch_size]
        texts = [c.content for c in batch]

        embeddings = embedder.embed_batch(
            texts,
            task_type="retrieval_document",
            batch_size=batch_size,
            delay_seconds=0, # Already handling delay in this loop
        )

        stored += db.upsert_many(batch, embeddings)
        
        # Respect Gemini rate limits (each chunk counts as 1 request)
        if i + batch_size < len(chunks):
            time.sleep(settings.embed_delay_seconds)

    print(f"[ingest] Done. Stored {stored} chunks in Supabase.")


if __name__ == "__main__":
    args = _parse_args()
    run(
        dry_run=args.dry_run,
        topic_filter=args.topic,
        resume=args.resume,
        batch_size=args.batch,
    )
