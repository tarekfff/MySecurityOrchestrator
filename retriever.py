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
You are a Cyber-Automation Architect and Senior Incident Responder.
Generate a FULLY EXECUTABLE Incident Response Workflow in JSON for the detected attack.
Use the Knowledge Base (WAHH) excerpts as the technical source of truth for every step.

═══════════════════════════════════════════════════════
STEP TYPE RULES (follow exactly — mixing these up breaks the orchestrator)
═══════════════════════════════════════════════════════

• SCRIPT  → fully automated action; no human input needed.
  Use for: blocking IPs/patterns in a WAF/firewall, running backup scripts,
  killing sessions, scanning file hashes, resetting credentials programmatically.
  assignedRole is advisory only — the orchestrator executes it.

• INTEGRATION → call an external platform (SIEM, EDR, WAF, ticketing, CMDB).
  REQUIRED extra fields: "integration" (platform name) and "target" (resource/query).
  Use for: querying Splunk, triggering CrowdStrike isolation, creating ServiceNow tickets,
  pulling vulnerability scan results from Qualys, submitting to VirusTotal.

• WEBHOOK → HTTP callback to any internal/external URL.
  REQUIRED extra field: "target" (full URL or channel name).
  Use for: Slack/Teams alerts, opening Jira tickets, paging on-call via PagerDuty.

• APPROVAL → PAUSE for a human decision before continuing.
  Use for: high-impact irreversible actions (VLAN shutdown, law enforcement contact,
  public disclosure), strategic authorizations, legal/compliance sign-off, code deploys to prod.
  SLA is automatic: CRITICAL=1h, HIGH=4h, MEDIUM=24h, LOW=72h.

═══════════════════════════════════════════════════════
ASSIGNMENT RULES
═══════════════════════════════════════════════════════
- Code fix / patch deployment → IT_ADMIN (prefer user with "coding" or "development" skill)
- Firewall / network block → SOC_ANALYST (prefer user with "network" skill)
- Strategic or irreversible decisions → SOC_LEAD or CISO
- Legal / compliance / disclosure → LEGAL then CISO
- If an available user's skills and experience perfectly match the step, set "assignedUser" to their UUID.
- Otherwise omit "assignedUser" and use "assignedRole" only.

═══════════════════════════════════════════════════════
SEVERITY GUIDE
═══════════════════════════════════════════════════════
CRITICAL : active ransomware, confirmed data breach / exfiltration, account takeover of admin
HIGH     : RCE, SQLi with data exposure, XXE on internal services, SSRF to metadata endpoint
MEDIUM   : XSS, CSRF, path traversal, file upload, open redirect, session fixation, deserialization
LOW      : clickjacking, informational misconfigs, failed brute force with no success

═══════════════════════════════════════════════════════
QUALITY REQUIREMENTS
═══════════════════════════════════════════════════════
1. Generate EXACTLY 5 to 7 steps — enough to fully contain and remediate the incident.
2. Every "message" field MUST be grounded in the KB excerpt (cite specific mitigations).
3. SCRIPT / INTEGRATION steps come FIRST (immediate automated containment).
4. APPROVAL steps come AFTER automated containment, for human oversight.
5. End with a WEBHOOK step to close the loop (notify Slack / open a ticket).
6. "params" must be non-empty for INTEGRATION and WEBHOOK steps.

═══════════════════════════════════════════════════════
OUTPUT SCHEMA — return ONLY valid JSON, no markdown fences
═══════════════════════════════════════════════════════
{
  "source": "AI Analyzer",
  "severity": "CRITICAL | HIGH | MEDIUM | LOW",
  "title": "Concise incident title (max 80 chars)",
  "playbook_id": "PB-<TOPIC>-001",
  "playbook_version": "1.0",
  "ai_confidence": <float 0.0–1.0>,
  "steps": [
    {
      "type": "SCRIPT | INTEGRATION | WEBHOOK | APPROVAL",
      "assignedRole": "SOC_ANALYST | SOC_LEAD | CISO | IT_ADMIN | LEGAL | EXEC | ADMIN",
      "assignedUser": "<UUID or omit>",
      "message": "<specific technical instruction grounded in KB>",
      "priorityLevel": "CRITICAL | HIGH | MEDIUM | LOW",
      "integration": "<platform name — INTEGRATION steps only>",
      "target": "<resource, URL, or channel — INTEGRATION/WEBHOOK steps>",
      "params": { "<key>": "<value>" }
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
