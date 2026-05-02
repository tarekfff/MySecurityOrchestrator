"""
Supabase client — upsert chunks and run similarity searches.

All vector operations go through the `match_cyber_chunks` RPC defined in
sql/schema.sql.  Call db.upsert_chunk() during ingestion and
db.similarity_search() during retrieval.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from supabase import Client, create_client

from chunker import Chunk


TABLE = "cyber_chunks"
PROFILES_TABLE = "profiles"


class SupabaseDB:
    def __init__(self, url: str, service_key: str):
        self.client: Client = create_client(url, service_key)

    # ── Write ─────────────────────────────────────────────────────────────────

    def upsert_chunk(self, chunk: Chunk, embedding: list[float]) -> dict:
        row = {
            "chunk_id":   chunk.chunk_id,
            "topic":      chunk.topic,
            "type":       chunk.type,
            "content":    chunk.content,
            "tags":       chunk.tags,
            "source":     chunk.source,
            "page_start": chunk.page_start,
            "page_end":   chunk.page_end,
            "embedding":  embedding,
        }
        resp = self.client.table(TABLE).upsert(row, on_conflict="chunk_id").execute()
        return resp.data[0] if resp.data else {}

    def upsert_many(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> int:
        rows = [
            {
                "chunk_id":   c.chunk_id,
                "topic":      c.topic,
                "type":       c.type,
                "content":    c.content,
                "tags":       c.tags,
                "source":     c.source,
                "page_start": c.page_start,
                "page_end":   c.page_end,
                "embedding":  emb,
            }
            for c, emb in zip(chunks, embeddings)
        ]
        resp = self.client.table(TABLE).upsert(rows, on_conflict="chunk_id").execute()
        return len(resp.data)

    # ── Read ──────────────────────────────────────────────────────────────────

    def similarity_search(
        self,
        query_embedding: list[float],
        k: int = 10,
        topic: Optional[str] = None,
        type_: Optional[str] = None,
        min_similarity: float = 0.0,
    ) -> list[dict]:
        resp = self.client.rpc(
            "match_cyber_chunks",
            {
                "query_embedding": query_embedding,
                "match_count":     k,
                "filter_topic":    topic,
                "filter_type":     type_,
                "min_similarity":  min_similarity,
            },
        ).execute()
        return resp.data or []

    def list_topics(self) -> list[dict]:
        resp = self.client.rpc("list_topics").execute()
        return resp.data or []

    def count_chunks(self) -> int:
        resp = (
            self.client.table(TABLE)
            .select("id", count="exact")
            .execute()
        )
        return resp.count or 0

    # ── Profiles ──────────────────────────────────────────────────────────────

    def list_active_profiles(self) -> list[dict]:
        """Fetch all active user profiles for the AI to assign tasks."""
        resp = (
            self.client.table(PROFILES_TABLE)
            .select("id, email, name, role, experience_level, skills, department")
            .eq("is_active", True)
            .execute()
        )
        return resp.data or []
