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

### Step 1 — Clone & Install

```bash
git clone <repo-url>
cd HackathoonEmbedder
pip install -r requirements.txt
```

### Step 2 — Configure Environment

```bash
cp .env.example .env
```

Fill in `.env`:

```env
# Required
GEMINI_API_KEY=your_gemini_api_key_here
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key_here
PDF_PATH=The Web Application Hacker's Handbook - ...pdf

# Webhook — receives every generated workflow AND error payloads
FRIEND_WEBHOOK_URL=http://localhost:3001/api/workflow/execute

# Ingestion tuning
EMBED_BATCH_SIZE=20
EMBED_DELAY_SECONDS=1.0
CHUNK_MAX_WORDS=250
CHUNK_MIN_WORDS=50

# API
API_HOST=0.0.0.0
API_PORT=8000
```

### Step 3 — Prepare Database

Open your **Supabase SQL Editor** and run both files in order:

```
sql/schema.sql       ← cyber_chunks table, ivfflat index, match_cyber_chunks RPC
sql/chat_schema.sql  ← chat sessions + messages tables (AI assistant feature)
```

`schema.sql` creates:
- `cyber_chunks` table with `vector(768)` column
- `ivfflat` cosine index (lists = 100)
- `match_cyber_chunks(query_embedding, match_count, filter_topic, filter_type, min_similarity)` RPC
- `list_topics()` RPC

### Step 4 — Run Ingestion

```bash
# Full ingestion: extract → chunk → embed → store (736 chunks, ~15 min on free tier)
python ingest.py

# Dry-run: parse + chunk only, no DB writes — use to verify chunking first
python ingest.py --dry-run

# Ingest a single topic only
python ingest.py --topic xss

# Resume: skip chunks already in DB — safe to re-run after interruption
python ingest.py --resume
```

### Step 5 — Start the API

```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Verify it's running:

```bash
curl http://localhost:8000/health
# {"status":"ok","chunk_count":736}
```

Interactive docs: `http://localhost:8000/docs`

### Step 6 — Run the Test Suite

See the full **[Testing](#testing)** section below.

---

## Testing

### Webhook & Error Pipeline Test

[scratch/test_error_webhook.py](scratch/test_error_webhook.py) is a self-contained test that:

1. Spins up a local HTTP webhook catcher on `127.0.0.1:9997`
2. Patches `FRIEND_WEBHOOK_URL` to point at the catcher (no `.env` change needed)
3. Runs **3 test cases** against the live `analyze` logic and prints exactly what the catcher received

**Requirements:** API does NOT need to be running — the test imports the logic directly.

```bash
python scratch/test_error_webhook.py
```

Expected output:

```
============================================================
Starting webhook catcher on http://127.0.0.1:9997
============================================================

[TEST 1] Simulating retrieval/embedding failure...
  ✅  Webhook received!
     error        : True
     incident_type: brute_force
     summary      : Analysis failed due to AI service error: Simulated rate-limit / embedding failure
     workflow     : None

[TEST 2] Simulating workflow generation failure...
  ✅  Webhook received!
     error        : True
     incident_type: SQL Injection
     summary      : Workflow generation failed: Simulated Gemini timeout during workflow generation
     workflow     : None

[TEST 3] Happy path — successful analysis (no error webhook expected)...
  ✅  Webhook received (successful workflow, not an error)
     title   : SSH Brute-Force Attack on Root Account Detected
     severity: HIGH
     steps   : 6 step(s)

============================================================
All tests complete.
============================================================
```

#### What each test covers

| Test | Scenario | Expected webhook |
|------|----------|-----------------|
| 1 | Embedding API throws (rate limit / outage) | `{ "error": true, "workflow": null }` |
| 2 | Workflow generation throws (Gemini timeout) | `{ "error": true, "workflow": null }` |
| 3 | Full success — real Gemini call | Valid workflow JSON with 5–7 steps |

#### Error webhook payload shape

When an error occurs the webhook receives:

```json
{
  "error": true,
  "incident_type": "brute_force",
  "summary": "Analysis failed due to AI service error: ...",
  "workflow": null,
  "retrieval": {
    "query": "sshd Multiple authentication failures ...",
    "topic_used": "brute_force",
    "chunks_found": 0,
    "grouped": {},
    "assembled_context": ""
  }
}
```

The receiving server checks `analysisData.workflow` — when `null` it returns `200` with "no automated actions recommended", so no crash or 422.

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

## Pre-generated Workflow Examples (`json_output/`)

The [json_output/](json_output/) folder contains **19 ready-to-use IR workflow JSON files**, one per attack type. These were generated by running `/analyze` against real Wazuh-style incidents and are the exact format accepted by the orchestrator and the Next.js webhook endpoint.

| File | Attack Type | Severity | Steps |
|------|-------------|----------|-------|
| [xss.json](json_output/xss.json) | Reflected XSS via search query parameter | HIGH | 6 |
| [sql_injection.json](json_output/sql_injection.json) | SQL Injection with data exposure | HIGH | 6 |
| [brute_force.json](json_output/brute_force.json) | SSH brute force on root account | CRITICAL | 6 |
| [csrf.json](json_output/csrf.json) | Cross-Site Request Forgery | MEDIUM | 5 |
| [rce.json](json_output/rce.json) | Remote Code Execution | CRITICAL | 6 |
| [path_traversal.json](json_output/path_traversal.json) | Directory traversal / LFI | HIGH | 5 |
| [session_management.json](json_output/session_management.json) | Session hijacking / fixation | HIGH | 5 |
| [access_control.json](json_output/access_control.json) | Broken access control / IDOR | HIGH | 5 |
| [xxe.json](json_output/xxe.json) | XML External Entity injection | HIGH | 6 |
| [ssrf.json](json_output/ssrf.json) | SSRF to internal metadata endpoint | HIGH | 6 |
| [clickjacking.json](json_output/clickjacking.json) | Clickjacking via missing X-Frame-Options | LOW | 4 |
| [open_redirect.json](json_output/open_redirect.json) | Open redirect phishing vector | MEDIUM | 5 |
| [file_upload.json](json_output/file_upload.json) | Malicious file upload (webshell) | CRITICAL | 6 |
| [deserialization.json](json_output/deserialization.json) | Insecure deserialization | HIGH | 6 |
| [business_logic.json](json_output/business_logic.json) | Business logic abuse | MEDIUM | 5 |
| [phishing.json](json_output/phishing.json) | Spear-phishing / credential harvesting | HIGH | 5 |
| [ransomware.json](json_output/ransomware.json) | Ransomware — mass encryption detected | CRITICAL | 6 |
| [data_breach.json](json_output/data_breach.json) | Data exfiltration / PII breach | CRITICAL | 6 |
| [ddos.json](json_output/ddos.json) | DDoS / SYN flood | HIGH | 5 |

### Workflow JSON structure

Every file follows this top-level schema:

```json
{
  "source": "AI Analyzer",
  "severity": "CRITICAL | HIGH | MEDIUM | LOW",
  "title": "Short incident title (max 80 chars)",
  "playbook_id": "PB-<TOPIC>-001",
  "playbook_version": "1.0",
  "ai_confidence": 0.95,
  "steps": [ ...5–7 step objects... ]
}
```

Each step contains:

```json
{
  "type": "SCRIPT | INTEGRATION | WEBHOOK | APPROVAL",
  "assignedRole": "SOC_ANALYST | SOC_LEAD | CISO | IT_ADMIN | LEGAL | EXEC | ADMIN",
  "assignedUser": "<UUID — only when a specific profile match was found>",
  "message": "Specific technical instruction grounded in the WAHH knowledge base",
  "priorityLevel": "CRITICAL | HIGH | MEDIUM | LOW",
  "integration": "<platform name — INTEGRATION steps only>",
  "target": "<resource or URL — INTEGRATION / WEBHOOK steps>",
  "params": { "<key>": "<extracted entity from the log>" }
}
```

### Send a pre-generated workflow to the orchestrator

```bash
# Pipe any file straight into the webhook endpoint
curl -X POST http://localhost:3001/api/workflow/execute \
  -H "Content-Type: application/json" \
  -d @json_output/brute_force.json
```

Or execute locally via `orchestrator.py`:

```bash
python orchestrator.py
# Edit the target_file path at the bottom of orchestrator.py to pick a different attack
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
