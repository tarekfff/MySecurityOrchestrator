"""
Retrieval interface for the multi-agent system.

Receives structured input from the Log Analyzer + Query Builder agents and
returns context assembled in the order the LLM Pipeline Agent expects:
    [INTRO] → [SYMPTOMS] → [DETECTION] → [EXPLOITATION] → [MITIGATION]

Typical call from an agent:

    from retriever import Retriever, RetrievalRequest

    r = Retriever()
    ctx = r.retrieve(RetrievalRequest(
        keywords=["script", "input", "alert", "browser"],
        suspected_attack="xss",
        context="web",
    ))
    # ctx.assembled_context  → ready to paste into LLM prompt
    # ctx.grouped            → dict[type → list[chunk]]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config import settings
from db import SupabaseDB
from embedder import GeminiEmbedder

# Preferred display order for the assembled context block
TYPE_ORDER = ["introduction", "symptoms", "detection", "exploitation", "mitigation", "general"]

_SECTION_LABEL = {
    "introduction": "OVERVIEW",
    "symptoms":     "SYMPTOMS / INDICATORS",
    "detection":    "DETECTION",
    "exploitation": "EXPLOITATION",
    "mitigation":   "MITIGATION",
    "general":      "ADDITIONAL CONTEXT",
}


# ── Request / Response models ─────────────────────────────────────────────────

@dataclass
class RetrievalRequest:
    keywords:         list[str]
    suspected_attack: Optional[str] = None   # normalised topic slug, e.g. "xss"
    context:          Optional[str] = None   # free text, e.g. "web", "network"
    k:                int           = 12     # total chunks to fetch
    min_similarity:   float         = 0.30


@dataclass
class RetrievalResult:
    query:             str
    topic_used:        Optional[str]
    raw_chunks:        list[dict]                   # as returned by Supabase
    grouped:           dict[str, list[dict]]        # type → chunks
    assembled_context: str                          # ready for LLM prompt


# ── Query builder ─────────────────────────────────────────────────────────────

def _build_query(request: RetrievalRequest) -> str:
    """
    Turn keywords + optional attack hint into a rich natural-language query.
    Better query text → better embedding → better retrieval.
    """
    parts = [" ".join(request.keywords)]
    if request.suspected_attack:
        parts.append(f"{request.suspected_attack} attack vulnerability")
    if request.context:
        parts.append(f"in {request.context} context")
    parts.append("detection symptoms mitigation exploitation")
    return " ".join(parts)


# ── Context assembler ─────────────────────────────────────────────────────────

def _group_by_type(chunks: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {t: [] for t in TYPE_ORDER}
    for chunk in chunks:
        t = chunk.get("type", "general")
        grouped.setdefault(t, []).append(chunk)
    return grouped


def _assemble(grouped: dict[str, list[dict]]) -> str:
    sections: list[str] = []
    for t in TYPE_ORDER:
        items = grouped.get(t, [])
        if not items:
            continue
        label = _SECTION_LABEL.get(t, t.upper())
        body = "\n\n".join(item["content"] for item in items)
        sections.append(f"[{label}]\n{body}")
    return "\n\n---\n\n".join(sections)


# ── Main retriever ────────────────────────────────────────────────────────────

class Retriever:
    def __init__(self):
        self._embedder = GeminiEmbedder(settings.gemini_api_key)
        self._db       = SupabaseDB(settings.supabase_url, settings.supabase_service_key)

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        query = _build_query(request)
        query_emb = self._embedder.embed_query(query)

        raw = self._db.similarity_search(
            query_embedding=query_emb,
            k=request.k,
            topic=request.suspected_attack,
            min_similarity=request.min_similarity,
        )

        # If topic filter returned nothing, retry without it
        if not raw and request.suspected_attack:
            raw = self._db.similarity_search(
                query_embedding=query_emb,
                k=request.k,
                min_similarity=request.min_similarity,
            )

        grouped           = _group_by_type(raw)
        assembled_context = _assemble(grouped)

        return RetrievalResult(
            query=query,
            topic_used=request.suspected_attack,
            raw_chunks=raw,
            grouped=grouped,
            assembled_context=assembled_context,
        )


# ── LLM prompt builder (convenience) ─────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a cybersecurity expert analyst.
You will be given security logs and a structured knowledge base excerpt.
Your task:
1. Identify the vulnerability or attack type present in the logs.
2. Explain it clearly and concisely.
3. List concrete mitigation steps.
4. If the evidence is ambiguous, say so — do not hallucinate.
"""

WORKFLOW_SYSTEM_PROMPT = """\
You are a Cyber-Automation Architect.
Your task is to generate a fully executable Incident Response Workflow in JSON format based on the detected incident and the provided Knowledge Base (WAHH).

### Assignment Logic:
- If a step is trivial or common (e.g. "turn off PC"), assign it to a 'SOC_ANALYST' or the user with the most appropriate skills.
- If it involves code changes, assign it to an 'IT_ADMIN' or someone with 'coding' skills.
- If it is a high-level attack or strategic decision, assign it to a 'SOC_LEAD' or 'CISO'.
- Match 'assignedUser' (UUID) if a specific user's skills/experience perfectly match the task. Otherwise use 'assignedRole'.

### Output Format:
You MUST output ONLY a valid JSON object following this schema:
{
  "source": "AI Analyzer",
  "severity": "LOW | MEDIUM | HIGH | CRITICAL",
  "title": "Clear Incident Title",
  "playbook_id": "PB-[TOPIC]-001",
  "ai_confidence": 0.0 to 1.0,
  "steps": [
    {
      "type": "APPROVAL | INTEGRATION | WEBHOOK | SCRIPT",
      "assignedRole": "SOC_ANALYST | SOC_LEAD | CISO | IT_ADMIN | LEGAL | EXEC | ADMIN",
      "assignedUser": "UUID (optional, use if skills match)",
      "message": "Specific instructions from the KB",
      "priorityLevel": "LOW | MEDIUM | HIGH | CRITICAL",
      "integration": "string (required for INTEGRATION, e.g. 'splunk')",
      "target": "string (required for INTEGRATION/WEBHOOK)",
      "params": {} (optional)
    }
  ]
}
"""


def build_llm_prompt(logs: str, result: RetrievalResult) -> str:
    return f"""{SYSTEM_PROMPT}

## Security Logs
{logs}

## Relevant Knowledge Base
{result.assembled_context}

## Your Analysis
"""


def build_workflow_prompt(logs: str, result: RetrievalResult, users: list[dict]) -> str:
    user_list = "\n".join([
        f"- {u['name']} ({u['role']}, {u['experience_level']}) ID: {u['id']}, Skills: {', '.join(u.get('skills', []))}"
        for u in users
    ])
    
    return f"""{WORKFLOW_SYSTEM_PROMPT}

## Available User Profiles
{user_list}

## Detected Incident Context (KB)
{result.assembled_context}

## Raw Security Logs
{logs}

## JSON Workflow Output:
"""
