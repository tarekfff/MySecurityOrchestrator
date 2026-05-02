"""
FastAPI application — exposes the retrieval pipeline as HTTP endpoints
for the multi-agent system to call.

Run:
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Endpoints
---------
GET  /health                 → liveness check + DB chunk count
GET  /topics                 → list indexed topics with chunk counts
POST /search                 → raw similarity search (debugging)
POST /retrieve               → full agent-ready retrieval (main endpoint)
POST /ingest/trigger         → kick off ingestion in a background thread
"""

from __future__ import annotations

import threading
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field
import httpx

from config import settings
from db import SupabaseDB
from embedder import GeminiEmbedder
from retriever import Retriever, RetrievalRequest, build_llm_prompt, build_workflow_prompt

app = FastAPI(
    title="CyberSec RAG API",
    description="Embedding retrieval pipeline over The Web Application Hacker's Handbook",
    version="1.0.0",
)

# Shared singletons — initialised once on first use
_retriever:  Retriever  | None = None
_db:         SupabaseDB | None = None
_embedder:   GeminiEmbedder | None = None


def _get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


def _get_db() -> SupabaseDB:
    global _db
    if _db is None:
        _db = SupabaseDB(settings.supabase_url, settings.supabase_service_key)
    return _db


def _get_embedder() -> GeminiEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = GeminiEmbedder(settings.gemini_api_key)
    return _embedder


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    chunk_count: int


class TopicEntry(BaseModel):
    topic: str
    chunk_count: int


class SearchRequest(BaseModel):
    query: str = Field(..., description="Free-text query to embed and search")
    k: int = Field(10, ge=1, le=50)
    topic: Optional[str] = Field(None, description="Filter by topic slug, e.g. 'xss'")
    type_: Optional[str] = Field(None, alias="type", description="Filter by chunk type")
    min_similarity: float = Field(0.0, ge=0.0, le=1.0)

    model_config = {"populate_by_name": True}


class SearchResult(BaseModel):
    chunk_id:   str
    topic:      str
    type:       str
    content:    str
    similarity: float
    page_start: Optional[int]
    page_end:   Optional[int]


class RetrieveRequest(BaseModel):
    keywords:         list[str] = Field(..., min_length=1, description="Keywords extracted by log analyzer")
    suspected_attack: Optional[str] = Field(None, description="Topic slug hint, e.g. 'xss'")
    context:          Optional[str] = Field(None, description="Context string, e.g. 'web', 'network'")
    k:                int   = Field(12, ge=1, le=50)
    min_similarity:   float = Field(0.30, ge=0.0, le=1.0)
    include_prompt:   bool  = Field(False, description="Also return an assembled LLM prompt (requires logs field)")
    logs:             Optional[str] = Field(None, description="Raw log content, used when include_prompt=True")


class RetrieveResponse(BaseModel):
    query:             str
    topic_used:        Optional[str]
    chunks_found:      int
    grouped:           dict[str, list[SearchResult]]
    assembled_context: str
    llm_prompt:        Optional[str] = None


class AnalyzeResponse(BaseModel):
    incident_type: str
    summary: str
    retrieval: RetrieveResponse
    workflow: Optional[dict] = Field(None, description="Generated executable workflow JSON")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_from_json(data: dict) -> tuple[list[str], Optional[str]]:
    """
    Extract keywords and suspected topic from a complex security log JSON.
    Handles both 'simple manual' and 'complex alert' formats.
    """
    keywords = []
    topic_hint = None

    # Try to find incident type / topic
    incident_type = (
        data.get("incident_type") or 
        data.get("alert", {}).get("incident_type") or
        data.get("alert", {}).get("category") or
        data.get("rule", {}).get("description")
    )
    
    if incident_type:
        topic_hint = str(incident_type).lower().replace(" ", "_").replace("_attack", "").replace("_email", "")
        keywords.append(str(incident_type))

    # Collect other fields as keywords
    for key in ["description", "technique", "tactic", "playbook"]:
        val = data.get(key) or data.get("rule", {}).get(key)
        if val:
            if isinstance(val, list):
                keywords.extend([str(v) for v in val])
            else:
                keywords.append(str(val))
    
    # MITRE IDs
    mitre = data.get("mitre_id") or data.get("rule", {}).get("mitre", {}).get("id")
    if mitre:
        if isinstance(mitre, list):
            keywords.extend([str(m) for m in mitre])
        else:
            keywords.append(str(mitre))

    # Fallback if keywords empty
    if not keywords:
        keywords = ["security", "incident"]

    return list(set(keywords)), topic_hint


class IngestStatus(BaseModel):
    status: str
    message: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health():
    db = _get_db()
    return HealthResponse(status="ok", chunk_count=db.count_chunks())


@app.get("/topics", response_model=list[TopicEntry])
def topics():
    db = _get_db()
    rows = db.list_topics()
    return [TopicEntry(topic=r["topic"], chunk_count=r["chunk_count"]) for r in rows]


@app.post("/search", response_model=list[SearchResult])
def search(req: SearchRequest):
    embedder = _get_embedder()
    db       = _get_db()

    query_emb = embedder.embed_query(req.query)
    rows = db.similarity_search(
        query_embedding=query_emb,
        k=req.k,
        topic=req.topic,
        type_=req.type_,
        min_similarity=req.min_similarity,
    )

    return [
        SearchResult(
            chunk_id=r["chunk_id"],
            topic=r["topic"],
            type=r["type"],
            content=r["content"],
            similarity=r["similarity"],
            page_start=r.get("page_start"),
            page_end=r.get("page_end"),
        )
        for r in rows
    ]


@app.post("/retrieve", response_model=RetrieveResponse)
def retrieve(req: RetrieveRequest):
    retriever = _get_retriever()

    result = retriever.retrieve(
        RetrievalRequest(
            keywords=req.keywords,
            suspected_attack=req.suspected_attack,
            context=req.context,
            k=req.k,
            min_similarity=req.min_similarity,
        )
    )

    grouped_out: dict[str, list[SearchResult]] = {}
    for type_, chunks in result.grouped.items():
        if chunks:
            grouped_out[type_] = [
                SearchResult(
                    chunk_id=c["chunk_id"],
                    topic=c["topic"],
                    type=c["type"],
                    content=c["content"],
                    similarity=c["similarity"],
                    page_start=c.get("page_start"),
                    page_end=c.get("page_end"),
                )
                for c in chunks
            ]

    llm_prompt = None
    if req.include_prompt and req.logs:
        llm_prompt = build_llm_prompt(req.logs, result)

    return RetrieveResponse(
        query=result.query,
        topic_used=result.topic_used,
        chunks_found=len(result.raw_chunks),
        grouped=grouped_out,
        assembled_context=result.assembled_context,
        llm_prompt=llm_prompt,
    )


# ── Webhook helper ────────────────────────────────────────────────────────────

async def _send_to_friend(workflow: dict):
    """Sends the generated workflow JSON to the friend's webhook."""
    if not settings.friend_webhook_url:
        return
    
    async with httpx.AsyncClient() as client:
        try:
            print(f"📡 Sending workflow to webhook: {settings.friend_webhook_url}")
            resp = await client.post(
                settings.friend_webhook_url, 
                json=workflow,
                timeout=10.0
            )
            print(f"✅ Webhook sent! Status: {resp.status_code}")
        except Exception as e:
            print(f"❌ Webhook failed: {e}")

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(incident: dict, background_tasks: BackgroundTasks):
    """
    Directly analyze a complex JSON incident log.
    Extracts keywords + topic, retrieves context, and prepares the AI flow.
    """
    # Try to find incident type / topic
    incident_type = (
        incident.get("incident_type") or 
        incident.get("alert", {}).get("incident_type") or
        incident.get("alert", {}).get("category") or
        incident.get("rule", {}).get("description") or
        "Unknown"
    )

    keywords, topic_hint = _extract_from_json(incident)
    
    # Map brute_force to authentication if needed, but our chunker now has brute_force
    
    retriever = _get_retriever()
    try:
        result = retriever.retrieve(
            RetrievalRequest(
                keywords=keywords,
                suspected_attack=topic_hint,
                k=15,
            )
        )
    except Exception as e:
        # Fallback if embedding fails (e.g. rate limit)
        return AnalyzeResponse(
            incident_type=str(incident_type or "Unknown"),
            summary=f"Analysis failed due to AI service error: {e}",
            retrieval=RetrieveResponse(
                query=" ".join(keywords),
                topic_used=topic_hint,
                chunks_found=0,
                grouped={},
                assembled_context="AI service unavailable."
            ),
            workflow=None
        )

    grouped_out: dict[str, list[SearchResult]] = {}
    for type_, chunks in result.grouped.items():
        if chunks:
            grouped_out[type_] = [
                SearchResult(
                    chunk_id=c["chunk_id"],
                    topic=c["topic"],
                    type=c["type"],
                    content=c["content"],
                    similarity=c["similarity"],
                    page_start=c.get("page_start"),
                    page_end=c.get("page_end"),
                )
                for c in chunks
            ]

    import json
    raw_log = json.dumps(incident, indent=2)
    llm_prompt = build_llm_prompt(raw_log, result)

    # ── Workflow Generation ──────────────────────────────────────────────────
    db = _get_db()
    embedder = _get_embedder()
    
    try:
        users = db.list_active_profiles()
    except Exception:
        # Fallback if table doesn't exist yet
        users = []

    workflow_prompt = build_workflow_prompt(raw_log, result, users)
    workflow_json = None
    try:
        workflow_json = embedder.generate_json(workflow_prompt)
    except Exception as e:
        import traceback
        print(f"Workflow generation failed: {e}")
        traceback.print_exc()

    ret_resp = RetrieveResponse(
        query=result.query,
        topic_used=result.topic_used,
        chunks_found=len(result.raw_chunks),
        grouped=grouped_out,
        assembled_context=result.assembled_context,
        llm_prompt=llm_prompt,
    )

    if workflow_json:
        background_tasks.add_task(_send_to_friend, workflow_json)

    return AnalyzeResponse(
        incident_type=str(incident_type),
        summary=f"Analysis of {incident_type} using {len(result.raw_chunks)} relevant KB chunks.",
        retrieval=ret_resp,
        workflow=workflow_json
    )


@app.post("/ingest/trigger", response_model=IngestStatus)
def ingest_trigger(background_tasks: BackgroundTasks, topic: Optional[str] = None):
    """
    Kick off the ingestion pipeline in a background thread.
    Safe to call multiple times — ingest.py uses --resume logic internally.
    """
    def _run():
        from ingest import run
        run(topic_filter=topic, resume=True)

    background_tasks.add_task(_run)
    msg = f"Ingestion started (topic={topic or 'all'})."
    return IngestStatus(status="accepted", message=msg)
