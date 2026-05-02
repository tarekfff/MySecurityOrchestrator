# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

RAG (Retrieval-Augmented Generation) pipeline over **The Web Application Hacker's Handbook (2nd Ed.)**.
It is a component of a multi-agent cybersecurity system:

```
Logs → Log Analyzer Agent → keywords + suspected_attack
                                ↓
                       Query Builder (retriever.py)
                                ↓
                    Gemini embedding → Supabase pgvector
                                ↓
                    Metadata-filtered similarity search
                                ↓
              Context Assembler (INTRO → SYMPTOMS → DETECTION → MITIGATION)
                                ↓
                          LLM Pipeline Agent
```

## Environment Setup

```bash
cp .env.example .env        # fill in GEMINI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
pip install -r requirements.txt
```

## Supabase Schema (run once)

Paste [sql/schema.sql](sql/schema.sql) into the Supabase SQL Editor.
Creates: `cyber_chunks` table (vector(768)), `match_cyber_chunks` RPC, `list_topics` RPC.

## Ingestion Pipeline

```bash
# Full ingestion
python ingest.py

# Dry-run (parse + chunk only, no DB writes — use this to verify chunking first)
python ingest.py --dry-run

# Only ingest one topic
python ingest.py --topic xss

# Skip chunks already stored (safe to re-run)
python ingest.py --resume
```

## API Server

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Interactive docs: `http://localhost:8000/docs`

Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness + total chunk count |
| GET | `/topics` | Topics indexed with chunk counts |
| POST | `/search` | Raw similarity search (debug) |
| POST | `/retrieve` | Main agent endpoint |
| POST | `/analyze` | Direct incident JSON analysis (Wazuh/Manual) |
| POST | `/ingest/trigger` | Kick off background ingestion |

### `/retrieve` — agent call example

```json
POST /retrieve
{
  "keywords": ["script", "input", "alert", "browser"],
  "suspected_attack": "xss",
  "context": "web",
  "k": 12,
  "min_similarity": 0.30,
  "include_prompt": true,
  "logs": "<paste raw log here>"
}
```

### `/analyze` — Dual-Process IR Pipeline

The `/analyze` endpoint executes two sequential AI processes to transform raw logs into actionable defense:

1.  **Step 1: RAG Diagnosis**:
    -   Extracts technical keywords and attack topics from the log.
    -   Retrieves relevant "how-to" context from the **Web Application Hacker's Handbook** (WAHH).
    -   Generates a technical summary and mitigation strategy.

2.  **Step 2: Workflow Synthesis**:
    -   Fetches active user profiles from the `profiles` DB table.
    -   Matches tasks to users based on **Role**, **Skills**, and **Experience**.
    -   Generates a strictly structured **JSON IR Workflow** following the `output.md` schema.

#### Accepted Input Formats

**1. Wazuh Alerts (Automatic Detection)**
The system automatically parses Wazuh JSON alerts by looking for `rule.description`, `data.srcip`, etc.
```json
{
  "rule": { "level": 10, "description": "sshd: authentication failure" },
  "data": { "srcip": "203.0.113.42", "dstuser": "root" }
}
```

**2. Admin Reports (Manual Input)**
Admins can send simple descriptive JSON for manual analysis.
```json
{
  "incident_type": "SQL Injection",
  "description": "Customer reported ' OR 1=1 appearing in error logs."
}
```

#### Results
The endpoint returns a unified `AnalyzeResponse` containing:
-   `incident_type`: Normalized attack type (e.g., "brute_force").
-   `summary`: Human-readable technical analysis.
-   `workflow`: The executable JSON plan for the `orchestrator.py`.

---

## Architecture — File Roles

| File | Role |
|------|------|
| [pdf_extractor.py](pdf_extractor.py) | PyMuPDF-based section extractor — detects headings by font size ratio |
| [chunker.py](chunker.py) | Maps sections → `topic` + `type` via keyword signals; splits into 50-250 word chunks with 20% overlap |
| [embedder.py](embedder.py) | Gemini `text-embedding-004` wrapper (768-dim); batching + retry built in |
| [db.py](db.py) | Supabase client — `upsert_many()` for ingestion, `similarity_search()` for retrieval |
| [ingest.py](ingest.py) | Orchestrates: extract → chunk → embed → store; supports `--dry-run`, `--topic`, `--resume` |
| [retriever.py](retriever.py) | Multi-agent retrieval interface: builds query from keywords, fetches + groups chunks, assembles prompt |
| [api.py](api.py) | FastAPI app; handles /analyze dual-process IR pipeline |
| [config.py](config.py) | Pydantic-settings config loaded from `.env` |
| [orchestrator.py](orchestrator.py) | Real-world execution engine for automated security tasks |
| [prompt_evolver.py](prompt_evolver.py) | Benchmarking system for AI prompt optimization & accuracy |
| [sql/schema.sql](sql/schema.sql) | Supabase DDL: table, ivfflat index, `match_cyber_chunks` RPC |

## Topic Taxonomy

Defined in `chunker.py → TOPIC_SIGNALS`. Topics: `xss`, `sql_injection`, `csrf`, `rce`,
`path_traversal`, `authentication`, `session_management`, `access_control`, `xxe`, `ssrf`,
`clickjacking`, `open_redirect`, `file_upload`, `deserialization`, `business_logic`,
`http_headers`, `information_disclosure`.

Add new topics by appending to `TOPIC_SIGNALS` — no other file needs changing.

## Chunk Type Taxonomy

Defined in `chunker.py → TYPE_PATTERNS`: `mitigation`, `exploitation`, `detection`,
`symptoms`, `introduction`, `general`.  Detected from section heading keywords.
Priority order: mitigation > exploitation > detection > symptoms > introduction > general.

## Calling the Retriever Directly (no HTTP)

```python
from retriever import Retriever, RetrievalRequest, build_llm_prompt

r = Retriever()
result = r.retrieve(RetrievalRequest(
    keywords=["script", "alert", "cookie", "input"],
    suspected_attack="xss",
))
prompt = build_llm_prompt(logs=raw_log_text, result=result)
```

## Embedding Model

- Model: `models/text-embedding-004` (Google Gemini)
- Dimensions: **768**
- `task_type="retrieval_document"` during ingestion
- `task_type="retrieval_query"` during search
- Free tier: 1 500 req/min — `embed_delay_seconds` in `.env` controls pacing
