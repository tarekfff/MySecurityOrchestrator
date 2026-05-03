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

import json
import threading
import uuid
from typing import AsyncGenerator, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import httpx
from google import genai
from google.genai import types as gtypes

from config import settings
from db import SupabaseDB
from embedder import GeminiEmbedder
from retriever import Retriever, RetrievalRequest, build_llm_prompt, build_workflow_prompt

app = FastAPI(
    title="CyberSec RAG API",
    description="Embedding retrieval pipeline over The Web Application Hacker's Handbook",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Conversation memory: conversation_id → list of {role, parts} dicts
_conversations: dict[str, list[dict]] = {}

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


# ── AI Assistant (streaming + Supabase persistence) ───────────────────────────

ASSIST_MODEL = "models/gemini-2.5-flash"

SYSTEM_PROMPT = """\
You are CyberGuard AI, an expert cybersecurity assistant specializing in web application security.
You have deep knowledge from The Web Application Hacker's Handbook and real-world incident response.

When helping a user with a security task:
- Give clear, actionable remediation steps
- Reference specific techniques (OWASP, CVEs, attack patterns) when relevant
- Explain the WHY behind mitigations, not just what to do
- Flag urgency level when appropriate (Critical / High / Medium / Low)
- Keep responses focused on the user's specific context

Respond in well-structured markdown.\
"""


class AssistStartRequest(BaseModel):
    user_id:          Optional[str] = Field(None, description="Profile ID or anonymous token")
    suspected_attack: Optional[str] = Field(None)
    task_context:     Optional[str] = Field(None, description="Raw incident log / ticket body")
    user_role:        Optional[str] = Field(None, description="e.g. 'SOC analyst'")


class AssistStartResponse(BaseModel):
    session_id: str
    title:      str


class SessionSummary(BaseModel):
    id:               str
    title:            str
    suspected_attack: Optional[str]
    user_role:        Optional[str]
    message_count:    int
    created_at:       str
    updated_at:       str
    last_message:     Optional[str]
    last_role:        Optional[str]


class SessionDetail(BaseModel):
    id:               str
    title:            str
    suspected_attack: Optional[str]
    task_context:     Optional[str]
    user_role:        Optional[str]
    message_count:    int
    created_at:       str
    updated_at:       str
    messages:         list[dict]


class RenameRequest(BaseModel):
    title: str


@app.post("/assist/sessions", response_model=AssistStartResponse)
def assist_create_session(req: AssistStartRequest):
    """
    Create a new chat session in Supabase.
    Returns session_id to use with /assist/stream.
    """
    db = _get_db()
    title = "New chat"
    if req.suspected_attack:
        title = f"{req.suspected_attack.replace('_', ' ').title()} — analysis"
    row = db.create_chat_session(
        user_id=req.user_id,
        title=title,
        suspected_attack=req.suspected_attack,
        task_context=req.task_context,
        user_role=req.user_role,
    )
    sid = row.get("id", str(uuid.uuid4()))
    _conversations[sid] = []
    return AssistStartResponse(session_id=sid, title=row.get("title", title))


@app.get("/assist/sessions", response_model=list[SessionSummary])
def assist_list_sessions(user_id: Optional[str] = None):
    """List all chat sessions, most-recent first. Pass user_id to filter."""
    db = _get_db()
    rows = db.list_chat_sessions(user_id=user_id)
    return [
        SessionSummary(
            id=r["id"],
            title=r["title"],
            suspected_attack=r.get("suspected_attack"),
            user_role=r.get("user_role"),
            message_count=r.get("message_count", 0),
            created_at=str(r["created_at"]),
            updated_at=str(r["updated_at"]),
            last_message=r.get("last_message"),
            last_role=r.get("last_role"),
        )
        for r in rows
    ]


@app.get("/assist/sessions/{session_id}", response_model=SessionDetail)
def assist_get_session(session_id: str):
    """Return full session metadata + all messages (for restoring a conversation)."""
    db = _get_db()
    session = db.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = db.get_chat_messages(session_id)
    return SessionDetail(
        id=session["id"],
        title=session["title"],
        suspected_attack=session.get("suspected_attack"),
        task_context=session.get("task_context"),
        user_role=session.get("user_role"),
        message_count=session.get("message_count", 0),
        created_at=str(session["created_at"]),
        updated_at=str(session["updated_at"]),
        messages=messages,
    )


@app.patch("/assist/sessions/{session_id}", response_model=dict)
def assist_rename_session(session_id: str, req: RenameRequest):
    """Rename a chat session."""
    db = _get_db()
    db.rename_chat_session(session_id, req.title.strip())
    return {"status": "ok", "title": req.title.strip()}


@app.delete("/assist/sessions/{session_id}")
def assist_delete_session(session_id: str):
    """Delete session from DB and clear in-memory history."""
    db = _get_db()
    db.delete_chat_session(session_id)
    _conversations.pop(session_id, None)
    return {"status": "deleted"}


@app.get("/assist/chat")
async def assist_chat(
    message: str,
    session_id: Optional[str] = None,
    task_context: Optional[str] = None,
    suspected_attack: Optional[str] = None,
    user_role: Optional[str] = None,
    user_id: Optional[str] = None,
):
    """
    Full response endpoint — Gemini 2.5 Flash, non-streaming.

    - Creates a DB session automatically if session_id is omitted.
    - Persists each user + assistant turn to chat_messages after completion.
    - Maintains in-memory history for multi-turn context within the process.

    Returns:
        { "session_id": "...", "title": "...", "reply": "..." }
    """
    db = _get_db()

    # Resolve or create session
    sid = session_id
    session_title = "New chat"
    is_new_session = False

    if not sid:
        is_new_session = True
        title = (message[:55] + "…") if len(message) > 55 else message
        row = db.create_chat_session(
            user_id=user_id,
            title=title,
            suspected_attack=suspected_attack,
            task_context=task_context,
            user_role=user_role,
        )
        sid = row.get("id") or str(uuid.uuid4())
        session_title = row.get("title", title)
    else:
        sess = db.get_chat_session(sid)
        if sess:
            session_title = sess.get("title", "Chat")

    # Restore in-memory history from DB if it's a resumed session
    if sid not in _conversations:
        history: list[dict] = []
        if not is_new_session:
            for msg in db.get_chat_messages(sid):
                gemini_role = "model" if msg["role"] == "assistant" else "user"
                history.append({"role": gemini_role, "parts": [{"text": msg["content"]}]})
        _conversations[sid] = history

    history = _conversations[sid]

    # RAG injection — pull relevant KB chunks for this message
    rag_context = ""
    if task_context or suspected_attack or message:
        try:
            retriever = _get_retriever()
            keywords = message.split()[:8]
            if task_context:
                keywords = task_context.split()[:8] + keywords
            result = retriever.retrieve(
                RetrievalRequest(
                    keywords=keywords,
                    suspected_attack=suspected_attack,
                    k=8,
                    min_similarity=0.28,
                )
            )
            if result.assembled_context:
                rag_context = (
                    "\n\n---\n**Relevant knowledge base context:**\n"
                    + result.assembled_context[:3000]
                    + "\n---\n"
                )
        except Exception:
            pass

    role_prefix = f"[User role: {user_role}] " if user_role else ""
    context_block = f"\n\nTask context:\n{task_context}" if task_context else ""
    # clean_message is what we store; full_user_text includes RAG and goes to the model
    clean_message = f"{role_prefix}{message}{context_block}"
    full_user_text = clean_message + rag_context

    history.append({"role": "user", "parts": [{"text": full_user_text}]})

    gemini = genai.Client(api_key=settings.gemini_api_key)
    try:
        response = gemini.models.generate_content(
            model=ASSIST_MODEL,
            contents=history,
            config=gtypes.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.4,
                max_output_tokens=2048,
            ),
        )
        full_reply = response.text or ""
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if full_reply:
        # Update in-memory history
        history.append({"role": "model", "parts": [{"text": full_reply}]})
        _conversations[sid] = history
        # Persist to Supabase
        try:
            db.save_chat_turn(
                session_id=sid,
                user_text=clean_message,
                assistant_text=full_reply,
            )
        except Exception as persist_err:
            print(f"[chat persist] {persist_err}")

    return {
        "session_id": sid,
        "title": session_title,
        "reply": full_reply
    }


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
