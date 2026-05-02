# CyberSec RAG Pipeline

A production-ready **Retrieval-Augmented Generation (RAG)** knowledge base built from *The Web Application Hacker's Handbook (2nd Ed.)*. Designed as a plug-in component for multi-agent cybersecurity systems.

Given a set of keywords and a suspected attack type extracted from security logs, it returns structured, LLM-ready context grouped by: **Overview → Symptoms → Detection → Exploitation → Mitigation**.

---

## How It Fits Into a Multi-Agent System

```
┌─────────────────────────────────────────────────────────────────┐
│                     Multi-Agent System                          │
│                                                                 │
│  [Log Input]                                                    │
│      │                                                          │
│      ▼                                                          │
│  ┌──────────────────┐                                           │
│  │  Log Analyzer    │  extracts keywords + suspected_attack     │
│  │  Agent           │  e.g. ["script","alert","cookie"] + "xss" │
│  └────────┬─────────┘                                           │
│           │  HTTP POST /retrieve   ◄──── THIS SERVICE           │
│           ▼                                                     │
│  ┌──────────────────┐                                           │
│  │  RAG API         │  embeds query → searches Supabase         │
│  │  (this repo)     │  → assembles structured context           │
│  └────────┬─────────┘                                           │
│           │  assembled_context + optional llm_prompt            │
│           ▼                                                     │
│  ┌──────────────────┐                                           │
│  │  LLM Pipeline    │  diagnoses attack, explains, mitigates    │
│  │  Agent           │                                           │
│  └──────────────────┘                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

- Python 3.10+
- A [Supabase](https://supabase.com) project (free tier is enough)
- A [Google AI Studio](https://aistudio.google.com) API key with access to `text-embedding-004`
- The source PDF in the project root

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
GEMINI_API_KEY=your_gemini_api_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key
```

### 3. Create the Supabase schema

In your Supabase dashboard → **SQL Editor**, run the contents of [`sql/schema.sql`](sql/schema.sql).

This creates:
- `cyber_chunks` table with a `vector(768)` column and an IVFFlat index
- `match_cyber_chunks(query_embedding, match_count, filter_topic, filter_type, min_similarity)` RPC for similarity search
- `list_topics()` RPC for topic inventory

### 4. Ingest the PDF

```bash
# Verify chunking without writing to DB
python ingest.py --dry-run

# Full ingestion (~734 chunks, ~37 embedding batches)
python ingest.py

# Resume safely if interrupted
python ingest.py --resume

# Ingest a single topic only
python ingest.py --topic xss
```

### 5. Start the API

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Interactive docs: **http://localhost:8000/docs**

---

## API Reference

### `GET /health`

Liveness check. Returns total chunk count in the database.

```json
{ "status": "ok", "chunk_count": 734 }
```

---

### `GET /topics`

Lists all indexed vulnerability topics and their chunk counts.

```json
[
  { "topic": "xss",            "chunk_count": 184 },
  { "topic": "rce",            "chunk_count": 165 },
  { "topic": "authentication", "chunk_count": 103 }
]
```

---

### `POST /retrieve` — Main agent endpoint

This is the endpoint your agents call.

**Request:**

```json
{
  "keywords": ["script", "input", "alert", "browser"],
  "suspected_attack": "xss",
  "context": "web",
  "k": 12,
  "min_similarity": 0.30,
  "include_prompt": true,
  "logs": "<paste raw log text here>"
}
```

| Field | Type | Description |
|---|---|---|
| `keywords` | `string[]` | Keywords extracted by the Log Analyzer agent |
| `suspected_attack` | `string` | Topic slug (see [Topic Taxonomy](#topic-taxonomy)). Optional but improves precision |
| `context` | `string` | Free-text context hint, e.g. `"web"`, `"network"`, `"auth"` |
| `k` | `int` | Number of chunks to retrieve (default: 12) |
| `min_similarity` | `float` | Cosine similarity threshold 0–1 (default: 0.30) |
| `include_prompt` | `bool` | If `true`, also returns a ready-to-send LLM prompt |
| `logs` | `string` | Raw log content — required when `include_prompt` is `true` |

**Response:**

```json
{
  "query": "script input alert browser xss attack vulnerability ...",
  "topic_used": "xss",
  "chunks_found": 10,
  "grouped": {
    "introduction": [ { "chunk_id": "...", "topic": "xss", "type": "introduction", "content": "...", "similarity": 0.91 } ],
    "symptoms":     [ ... ],
    "detection":    [ ... ],
    "exploitation": [ ... ],
    "mitigation":   [ ... ]
  },
  "assembled_context": "[OVERVIEW]\n...\n\n---\n\n[SYMPTOMS / INDICATORS]\n...",
  "llm_prompt": "You are a cybersecurity expert...\n## Security Logs\n...\n## Relevant Knowledge Base\n..."
}
```

---

### `POST /search` — Debug endpoint

Raw similarity search without grouping. Useful during development to inspect retrieved chunks.

```json
{
  "query": "SQL union select bypass WAF",
  "k": 5,
  "topic": "sql_injection",
  "type": "exploitation",
  "min_similarity": 0.4
}
```

---

### `POST /ingest/trigger`

Kicks off the ingestion pipeline as a background task. Safe to call multiple times (uses `--resume` logic).

```bash
curl -X POST "http://localhost:8000/ingest/trigger?topic=xss"
```

---

### `POST /analyze` — Direct Incident Analysis

Analyzes a complex security log JSON (e.g., from Wazuh, SIEM, or manual input), extracts keywords, and generates a retrieval-augmented "AI Flow".

**Request:**

```json
{
  "alert": {
    "incident_type": "Brute Force Attack",
    "category": "brute_force"
  },
  "rule": {
    "description": "sshd: Multiple authentication failures",
    "mitre": { "id": ["T1110.003"] }
  },
  "data": { "srcip": "203.0.113.42", "dstuser": "root" }
}
```

**Response:**

```json
{
  "incident_type": "Brute Force Attack",
  "summary": "Analysis of Brute Force Attack using 15 relevant KB chunks.",
  "retrieval": {
    "query": "sshd: Multiple authentication failures T1110.003 brute force ...",
    "topic_used": "brute_force",
    "chunks_found": 15,
    "grouped": { ... },
    "assembled_context": "[OVERVIEW]\n...\n",
    "llm_prompt": "You are a cybersecurity expert...\n## Security Logs\n...\n## Relevant Knowledge Base\n..."
  }
}
```

---

## Integration Examples

### Python (direct library import — no HTTP overhead)

Use this when your agent runs in the same process or the same Python environment:

```python
from retriever import Retriever, RetrievalRequest, build_llm_prompt

retriever = Retriever()

result = retriever.retrieve(RetrievalRequest(
    keywords=["union", "select", "error", "database"],
    suspected_attack="sql_injection",
    context="web",
    k=10,
    min_similarity=0.35,
))

# Use grouped context directly
for chunk in result.grouped["mitigation"]:
    print(chunk["content"])

# Or build a full LLM prompt
prompt = build_llm_prompt(logs=raw_log_text, result=result)
# → send `prompt` to your LLM
```

### HTTP (any language / any agent framework)

```python
import httpx

response = httpx.post("http://localhost:8000/retrieve", json={
    "keywords": ["privilege", "escalation", "admin", "bypass"],
    "suspected_attack": "access_control",
    "k": 8,
    "include_prompt": True,
    "logs": raw_log_text,
})

data = response.json()
llm_prompt = data["llm_prompt"]          # send to your LLM
context    = data["assembled_context"]   # or use the raw context
```

### LangChain agent tool

```python
from langchain.tools import tool
import httpx

RAG_URL = "http://localhost:8000"

@tool
def query_cybersec_kb(keywords: list[str], suspected_attack: str, logs: str) -> str:
    """Query the cybersecurity knowledge base and return structured context for the LLM."""
    resp = httpx.post(f"{RAG_URL}/retrieve", json={
        "keywords": keywords,
        "suspected_attack": suspected_attack,
        "include_prompt": False,
        "k": 10,
    })
    return resp.json()["assembled_context"]
```

### n8n / Make / Zapier

Call `POST /retrieve` as an HTTP node with JSON body. Map `assembled_context` from the response into your next LLM node's prompt.

---

## Topic Taxonomy

These are the valid values for `suspected_attack` in API requests.

| Slug | Covers |
|---|---|
| `xss` | Cross-Site Scripting (reflected, stored, DOM) |
| `sql_injection` | SQL injection, blind SQLi, union-based |
| `csrf` | Cross-Site Request Forgery |
| `rce` | Remote Code Execution, OS command injection |
| `path_traversal` | Directory traversal, LFI, RFI |
| `authentication` | Brute force, credential attacks, MFA bypass |
| `brute_force` | Password guessing, dictionary attacks, credential stuffing |
| `phishing` | Malicious emails, spearphishing, malicious attachments |
| `ransomware` | Mass encryption, shadow copy deletion, data kidnapping |
| `data_breach` | Data exfiltration, sensitive data leakage, database leaks |
| `ddos` | Denial of Service, SYN floods, network floods |
| `session_management` | Session fixation/hijacking, cookie security, JWT |
| `access_control` | IDOR, privilege escalation, broken access control |
| `xxe` | XML External Entity injection |
| `ssrf` | Server-Side Request Forgery |
| `clickjacking` | UI redressing, iframe overlay |
| `open_redirect` | Unvalidated redirects |
| `file_upload` | Unrestricted file upload |
| `deserialization` | Insecure deserialization |
| `business_logic` | Logic flaws, workflow bypass |
| `http_headers` | CSP, HSTS, CORS misconfiguration |
| `information_disclosure` | Verbose errors, stack traces, source disclosure |

To add a new topic: append an entry to `TOPIC_SIGNALS` in [`chunker.py`](chunker.py) and re-run `python ingest.py --resume`.

---

## Chunk Type Taxonomy

Each chunk is classified into one of these types. The `/retrieve` endpoint groups and orders them automatically.

| Type | Meaning |
|---|---|
| `introduction` | What the vulnerability is, how it works |
| `symptoms` | Signs and indicators of compromise |
| `detection` | How to find / test for the vulnerability |
| `exploitation` | Attack techniques, payloads, bypass methods |
| `mitigation` | Prevention, defense, secure coding guidance |
| `general` | Supporting context that doesn't fit other types |

---

## Architecture

```
pdf_extractor.py   PDF → Section[]        (pdfplumber, font-size heading detection)
       │
chunker.py         Section[] → Chunk[]    (topic + type classification, sliding window)
       │
embedder.py        Chunk[] → vector[]     (Gemini text-embedding-004, 768-dim, batched)
       │
db.py              vector[] → Supabase    (pgvector upsert + similarity search RPC)
       │
retriever.py       keywords → context     (query builder + context assembler)
       │
api.py             FastAPI HTTP layer     (/retrieve, /search, /topics, /health)
```

---

## Project Files

```
.
├── api.py                  FastAPI application
├── chunker.py              Topic/type classifier + chunking logic
├── config.py               Pydantic-settings loader (.env)
├── db.py                   Supabase client (upsert + similarity search)
├── embedder.py             Gemini text-embedding-004 wrapper
├── ingest.py               Ingestion pipeline script
├── pdf_extractor.py        PDF → structured sections
├── retriever.py            Multi-agent retrieval interface
├── requirements.txt
├── .env.example
└── sql/
    └── schema.sql          Supabase DDL (run once before ingestion)
```

---

## Knowledge Base Stats (after ingestion)

| Topic | Chunks |
|---|---|
| XSS | 184 |
| RCE | 165 |
| Authentication | 103 |
| Session Management | 77 |
| Access Control | 52 |
| SQL Injection | 50 |
| Information Disclosure | 35 |
| CSRF | 25 |
| Path Traversal | 19 |
| Business Logic | 10 |
| Open Redirect | 7 |
| XXE | 6 |
| File Upload | 1 |
| **Total** | **734** |

---

## Source

Knowledge base derived from:

> *The Web Application Hacker's Handbook: Finding and Exploiting Security Flaws, 2nd Edition*
> Dafydd Stuttard & Marcus Pinto — Wiley, 2011
# MySecurityOrchestrator
