# CyberGuard AI — Automated Incident Response Platform

> **AI-Powered Incident Response: From Raw Logs to Automated Mitigation.**

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Gemini](https://img.shields.io/badge/Gemini_2.5_Flash-AI-blue?style=flat)](https://aistudio.google.com/)
[![Supabase](https://img.shields.io/badge/Supabase-pgvector-green?style=flat&logo=supabase)](https://supabase.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-yellow?style=flat&logo=python)](https://python.org)

---

## Problem

Cybersecurity teams are overwhelmed by thousands of alerts daily. Responding requires deep expertise, manual lookup of security handbooks, and complex coordination between roles (CISO, SOC, IT Admin, Legal). This leads to slow response times and human error.

## Solution

A **RAG (Retrieval-Augmented Generation) orchestrator** that ingests raw security logs (Wazuh, SIEM, manual reports), diagnoses the attack using expert knowledge from *The Web Application Hacker's Handbook (2nd Ed.)*, and generates **executable, role-assigned Incident Response Workflows** in seconds.

---

## System Architecture

```
Raw Logs (Wazuh / Manual)
        │
        ▼
   /analyze endpoint
        │
   ┌────┴────────────────────────────────────────────────┐
   │  Step 1 — RAG Diagnosis                             │
   │  keywords + attack hint → Gemini embedding          │
   │  → Supabase pgvector similarity search              │
   │  → Context assembled: INTRO → SYMPTOMS → DETECTION  │
   │                         → EXPLOITATION → MITIGATION │
   └────┬────────────────────────────────────────────────┘
        │
   ┌────┴────────────────────────────────────────────────┐
   │  Step 2 — Workflow Synthesis                        │
   │  Fetch active profiles from DB                      │
   │  Match tasks by Role + Skills + Experience          │
   │  → Gemini generates structured JSON IR Workflow     │
   └────┬────────────────────────────────────────────────┘
        │
        ▼
   JSON Workflow → Webhook → Orchestrator / Dashboard
```

```mermaid
graph TD
    subgraph "Ingestion Layer"
        PDF[WAHH PDF] --> EXT[PDF Extractor]
        EXT --> CHK[Smart Chunker]
        CHK --> EMB[Gemini Embedder]
        EMB --> VDB[(Supabase pgvector)]
    end

    subgraph "AI Analysis Layer"
        LOGS[Raw Incident Logs] --> ANL[analyze endpoint]
        ANL --> RET[Retriever]
        VDB --> RET
        RET --> GEM[Gemini 2.5 Flash]
    end

    subgraph "Orchestration & Execution"
        GEM --> WF[JSON Workflow]
        WF --> DSB[Command Dashboard]
        WF --> ORC[orchestrator.py]
        ORC --> SYS[System Mitigation]
    end

    subgraph "Human-in-the-Loop"
        DSB --> APP[Manual Approval]
        APP --> ORC
    end
```

---

## Key Features

### Expert RAG Intelligence
Searches over **736 specialized knowledge chunks** from *The Web Application Hacker's Handbook* to retrieve exact symptoms and mitigation steps for the detected attack — no hallucination, grounded in the security bible.

### Intelligent Task Assignment
Workflows assign tasks to the right person based on:
- **Role** — CISO for strategic decisions, IT Admin for code fixes, SOC Analyst for network blocks
- **Skills** — matches "Python", "network", "mitigation" skills to relevant steps
- **Experience Level** — junior vs. senior step allocation

### Real-World Orchestration (`orchestrator.py`)
- Automatic IP blocking via `pfctl` (macOS) or `iptables` (Linux)
- Code patching simulation
- Webhook sharing to teammates (Slack, ticketing, etc.)

### AI Chat Assistant (`/assist/stream`)
- Streaming SSE endpoint powered by Gemini 2.5 Flash
- RAG-augmented responses pull relevant KB chunks per message
- Full session persistence in Supabase with multi-turn context

### 19+ Attack Types Supported
`xss`, `sql_injection`, `csrf`, `rce`, `path_traversal`, `authentication`, `brute_force`, `session_management`, `access_control`, `xxe`, `ssrf`, `clickjacking`, `open_redirect`, `file_upload`, `deserialization`, `business_logic`, `phishing`, `ransomware`, `data_breach`, `ddos`

---

## Getting Started

### 1. Clone & Install

```bash
git clone <repo-url>
cd HackathoonEmbedder
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
GEMINI_API_KEY=your_gemini_api_key_here
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key_here
PDF_PATH=The Web Application Hacker's Handbook - ...pdf

# Optional: forward workflows to a webhook
FRIEND_WEBHOOK_URL=https://hooks.slack.com/services/...

# Ingestion tuning
EMBED_BATCH_SIZE=20
EMBED_DELAY_SECONDS=1.0
CHUNK_MAX_WORDS=250
CHUNK_MIN_WORDS=50
```

### 3. Prepare Database

Paste [sql/schema.sql](sql/schema.sql) into your **Supabase SQL Editor**. This creates:
- `cyber_chunks` table with `vector(768)` column
- `ivfflat` index for fast cosine similarity
- `match_cyber_chunks` RPC for filtered vector search
- `list_topics` RPC for topic inventory

For the AI chat feature, also run [sql/chat_schema.sql](sql/chat_schema.sql).

### 4. Run Ingestion

```bash
# Full ingestion (extract → chunk → embed → store)
python ingest.py

# Dry-run — parse + chunk only, no DB writes
python ingest.py --dry-run

# Ingest a single topic
python ingest.py --topic xss

# Resume — skip already-stored chunks (safe to re-run)
python ingest.py --resume
```

### 5. Start the API

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Interactive docs: `http://localhost:8000/docs`

---

## API Reference

### Core Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check + total chunk count |
| `GET` | `/topics` | Topics indexed with chunk counts |
| `POST` | `/search` | Raw similarity search (debug) |
| `POST` | `/retrieve` | Agent-ready retrieval with assembled context |
| `POST` | `/analyze` | Dual-process IR pipeline — diagnosis + workflow |
| `POST` | `/ingest/trigger` | Kick off background ingestion |

### Chat / Assist Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/assist/sessions` | Create a new chat session |
| `GET` | `/assist/sessions` | List all sessions (filter by `user_id`) |
| `GET` | `/assist/sessions/{id}` | Get session + full message history |
| `PATCH` | `/assist/sessions/{id}` | Rename session |
| `DELETE` | `/assist/sessions/{id}` | Delete session |
| `GET` | `/assist/stream` | SSE streaming chat (RAG-augmented) |

---

### `/retrieve` — Agent call example

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

**Response:**
```json
{
  "query": "script input alert browser xss attack vulnerability ...",
  "topic_used": "xss",
  "chunks_found": 12,
  "grouped": {
    "introduction": [...],
    "symptoms": [...],
    "mitigation": [...]
  },
  "assembled_context": "[OVERVIEW]\n...\n\n---\n\n[MITIGATION]\n...",
  "llm_prompt": "You are a cybersecurity expert analyst..."
}
```

---

### `/analyze` — Dual-Process IR Pipeline

Accepts two input formats:

**Wazuh Alert (auto-detected):**
```json
POST /analyze
{
  "rule": { "level": 10, "description": "sshd: authentication failure" },
  "data": { "srcip": "203.0.113.42", "dstuser": "root" }
}
```

**Admin Manual Report:**
```json
POST /analyze
{
  "incident_type": "SQL Injection",
  "description": "Customer reported ' OR 1=1 appearing in error logs."
}
```

**Response (`AnalyzeResponse`):**
```json
{
  "incident_type": "sql_injection",
  "summary": "Analysis of sql_injection using 15 relevant KB chunks.",
  "retrieval": { ... },
  "workflow": {
    "source": "AI Analyzer",
    "severity": "HIGH",
    "title": "SQL Injection Detected — Immediate Containment Required",
    "playbook_id": "PB-SQL_INJECTION-001",
    "ai_confidence": 0.91,
    "steps": [ ... ]
  }
}
```

---

## Workflow Schema

The generated workflow follows the schema defined in [output.md](output.md).

### Step Types

| Type | Description |
|------|-------------|
| `SCRIPT` | Automated action — runs immediately, no human input (IP blocks, session kills, credential resets) |
| `INTEGRATION` | Calls an external platform (Splunk, CrowdStrike, ServiceNow, Qualys) |
| `WEBHOOK` | HTTP callback to any URL (Slack, Jira, PagerDuty) |
| `APPROVAL` | Pauses for human decision — irreversible or high-impact actions |

### Automatic SLA (APPROVAL steps)

| Severity | Deadline |
|----------|----------|
| `CRITICAL` | 1 hour |
| `HIGH` | 4 hours |
| `MEDIUM` | 24 hours |
| `LOW` | 72 hours |

### Example Workflow — Ransomware Response

```json
{
  "source": "EDR — CrowdStrike",
  "severity": "CRITICAL",
  "title": "Ransomware Detected on Finance Servers",
  "playbook_id": "PB-RANSOMWARE-001",
  "ai_confidence": 0.97,
  "steps": [
    {
      "type": "SCRIPT",
      "assignedRole": "SOC_ANALYST",
      "message": "Execute host-isolation script on FIN-SRV-01, FIN-SRV-02.",
      "priorityLevel": "CRITICAL"
    },
    {
      "type": "INTEGRATION",
      "integration": "veeam",
      "target": "backup-job/finance-servers",
      "message": "Trigger emergency snapshot before remediation.",
      "assignedRole": "IT_ADMIN"
    },
    {
      "type": "APPROVAL",
      "assignedRole": "CISO",
      "message": "CISO authorization required before notifying law enforcement.",
      "priorityLevel": "CRITICAL"
    }
  ]
}
```

---

## Project Structure

| File | Role |
|------|------|
| [api.py](api.py) | FastAPI app — all HTTP endpoints, dual-process IR pipeline, SSE chat |
| [retriever.py](retriever.py) | RAG logic — query building, vector search, context assembly |
| [embedder.py](embedder.py) | Gemini `text-embedding-004` wrapper (768-dim), batching + retry |
| [db.py](db.py) | Supabase client — `upsert_many()`, `similarity_search()`, chat persistence |
| [ingest.py](ingest.py) | Orchestrates: extract → chunk → embed → store |
| [chunker.py](chunker.py) | Maps PDF sections → `topic` + `type`; splits into 50–250 word chunks |
| [pdf_extractor.py](pdf_extractor.py) | PyMuPDF-based section extractor — detects headings by font size ratio |
| [orchestrator.py](orchestrator.py) | Real-world execution engine for automated security tasks |
| [prompt_evolver.py](prompt_evolver.py) | Benchmarking system for AI prompt optimization & accuracy |
| [config.py](config.py) | Pydantic-settings config loaded from `.env` |
| [sql/schema.sql](sql/schema.sql) | Supabase DDL: `cyber_chunks` table, ivfflat index, `match_cyber_chunks` RPC |
| [sql/chat_schema.sql](sql/chat_schema.sql) | Supabase DDL for chat sessions and messages |
| [output.md](output.md) | Workflow payload reference and JSON schema |
| [json_output/](json_output/) | Pre-generated workflow examples for all 19+ attack types |

---

## Taxonomy Reference

### Topics (`chunker.py → TOPIC_SIGNALS`)

`xss` · `sql_injection` · `csrf` · `rce` · `path_traversal` · `authentication` · `brute_force` · `session_management` · `access_control` · `xxe` · `ssrf` · `clickjacking` · `open_redirect` · `file_upload` · `deserialization` · `business_logic` · `phishing` · `ransomware` · `data_breach` · `ddos`

To add a new topic, append to `TOPIC_SIGNALS` in [chunker.py](chunker.py) — no other file needs changing.

### Chunk Types (`chunker.py → TYPE_PATTERNS`)

Priority order: `mitigation` > `exploitation` > `detection` > `symptoms` > `introduction` > `general`

---

## Calling the Retriever Directly (no HTTP)

```python
from retriever import Retriever, RetrievalRequest, build_llm_prompt

r = Retriever()
result = r.retrieve(RetrievalRequest(
    keywords=["script", "alert", "cookie", "input"],
    suspected_attack="xss",
))

# Use assembled context in your own prompt
prompt = build_llm_prompt(logs=raw_log_text, result=result)
```

---

## Embedding Model

| Property | Value |
|----------|-------|
| Model | `models/text-embedding-004` (Google Gemini) |
| Dimensions | 768 |
| Ingestion `task_type` | `retrieval_document` |
| Query `task_type` | `retrieval_query` |
| Free tier | 1,500 req/min |
| Rate limiting | `EMBED_DELAY_SECONDS` in `.env` |

---

## Technical Rationale

- **AI Engine**: Google Gemini 2.5 Flash — generous free tier, high-performance embeddings and reasoning, cost-effective for development and production
- **Vector DB**: Supabase Cloud with `pgvector` and `ivfflat` index — rapid prototyping, zero infrastructure overhead; architecture supports self-hosted Supabase (Docker) for production data sovereignty
- **Knowledge Source**: *The Web Application Hacker's Handbook (2nd Ed.)* — 736 chunks covering 19+ attack types, from the industry's de facto security reference

---

## Future Roadmap

- [ ] Direct integration with AWS/GCP/Azure Firewalls
- [ ] Collaborative workflow editing for response teams
- [ ] Multi-source ingestion (OWASP Top 10, NIST SP 800-61, CVE advisories)
- [ ] Self-hosted Supabase deployment guide (Docker Compose)
- [ ] Real-time Wazuh agent webhook integration
