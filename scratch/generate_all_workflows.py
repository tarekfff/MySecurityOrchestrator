"""
Standalone batch generator — produces one workflow JSON per attack type.
Calls the retriever + Gemini directly (no HTTP server needed).

Usage:
    python scratch/generate_all_workflows.py

Output: json_output/<attack>.json  (overwrites existing files)
"""

from __future__ import annotations

import json
import os
import sys
import time

# Make the project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from db import SupabaseDB
from embedder import GeminiEmbedder
from retriever import Retriever, RetrievalRequest, build_workflow_prompt

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "json_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

INCIDENTS: dict[str, dict] = {
    "xss": {
        "incident_type": "Cross-Site Scripting (XSS)",
        "alert": {"category": "xss"},
        "description": "Detected <script>alert(1)</script> in the search query parameter.",
        "location": "https://example.com/search?q=<script>alert(1)</script>",
    },
    "sql_injection": {
        "incident_type": "SQL Injection",
        "alert": {"category": "sql_injection"},
        "description": "Detected ' OR '1'='1 in the login form username field with data returned in response.",
        "data": {"dstuser": "' OR '1'='1"},
    },
    "csrf": {
        "incident_type": "CSRF",
        "alert": {"category": "csrf"},
        "description": "State-changing request received without a valid anti-CSRF token.",
        "location": "/api/v1/user/update_email",
    },
    "rce": {
        "incident_type": "Remote Code Execution",
        "alert": {"category": "rce"},
        "description": "Attempted OS command injection via shell metacharacters: ; cat /etc/passwd",
        "data": {"payload": "; cat /etc/passwd"},
    },
    "path_traversal": {
        "incident_type": "Path Traversal",
        "alert": {"category": "path_traversal"},
        "description": "Access attempt to sensitive file using ../../etc/shadow",
        "location": "/download?file=../../etc/shadow",
    },
    "brute_force": {
        "incident_type": "Brute Force",
        "alert": {"category": "brute_force"},
        "description": "Multiple failed login attempts for user 'admin' from IP 203.0.113.42",
        "data": {"srcip": "203.0.113.42", "dstuser": "admin"},
    },
    "phishing": {
        "incident_type": "Phishing",
        "alert": {"category": "phishing"},
        "description": "User reported a suspicious email from 'it-support-portal.net' requesting password reset.",
        "data": {"domain": "it-support-portal.net"},
    },
    "ransomware": {
        "incident_type": "Ransomware",
        "alert": {"category": "ransomware"},
        "description": "Mass file encryption detected on FileServer-01. Extension changed to .locked",
        "data": {"host": "FileServer-01", "extension": ".locked"},
    },
    "data_breach": {
        "incident_type": "Data Breach",
        "alert": {"category": "data_breach"},
        "description": "Unusually high data exfiltration to external IP 45.33.12.98 detected by DLP.",
        "data": {"dest_ip": "45.33.12.98", "volume": "5GB"},
    },
    "ddos": {
        "incident_type": "DDoS",
        "alert": {"category": "ddos"},
        "description": "Traffic spike detected: 100,000 requests/sec from 500 different IPs.",
        "data": {"rps": 100000},
    },
    "session_management": {
        "incident_type": "Session Management Flaw",
        "alert": {"category": "session_management"},
        "description": "Session fixation attempt: application accepted a user-provided session ID.",
        "data": {"session_id": "FIXED_ID_123"},
    },
    "access_control": {
        "incident_type": "Access Control Violation (IDOR)",
        "alert": {"category": "access_control"},
        "description": "User A attempted to access User B's profile via direct ID manipulation.",
        "location": "/user/profile/5001",
    },
    "xxe": {
        "incident_type": "XML External Entity (XXE)",
        "alert": {"category": "xxe"},
        "description": "XML upload contains an external entity reference to /etc/hostname",
        "data": {"payload": "<!ENTITY xxe SYSTEM 'file:///etc/hostname'>"},
    },
    "ssrf": {
        "incident_type": "SSRF",
        "alert": {"category": "ssrf"},
        "description": "Request to internal metadata service from the application server.",
        "location": "http://169.254.169.254/latest/meta-data/",
    },
    "clickjacking": {
        "incident_type": "Clickjacking",
        "alert": {"category": "clickjacking"},
        "description": "Security audit found X-Frame-Options header missing on critical pages.",
        "location": "/payments/checkout",
    },
    "open_redirect": {
        "incident_type": "Open Redirect",
        "alert": {"category": "open_redirect"},
        "description": "Unvalidated redirect found in the login redirection parameter.",
        "location": "/login?redirect=http://attacker.com",
    },
    "file_upload": {
        "incident_type": "Unrestricted File Upload",
        "alert": {"category": "file_upload"},
        "description": "PHP web shell uploaded as shell.php.jpg",
        "data": {"filename": "shell.php.jpg"},
    },
    "deserialization": {
        "incident_type": "Insecure Deserialization",
        "alert": {"category": "deserialization"},
        "description": "Suspicious Java serialized object detected in the 'JSESSIONID' cookie.",
        "data": {"cookie": "rO0ABXNyA..."},
    },
    "business_logic": {
        "incident_type": "Business Logic Flaw",
        "alert": {"category": "business_logic"},
        "description": "Negative price used in the shopping cart checkout process.",
        "data": {"price": -100.0},
    },
}

# Seconds between API calls to stay within Gemini free-tier limits
DELAY_BETWEEN = 8.0


def extract_keywords_and_topic(incident: dict) -> tuple[list[str], str | None]:
    keywords = []
    topic_hint = (
        incident.get("alert", {}).get("category")
        or incident.get("incident_type", "")
    )
    topic_hint = topic_hint.lower().replace(" ", "_").replace("_attack", "")

    for key in ["incident_type", "description"]:
        val = incident.get(key)
        if val:
            keywords.append(str(val))

    data = incident.get("data", {})
    for v in data.values():
        if isinstance(v, str):
            keywords.append(v)

    loc = incident.get("location")
    if loc:
        keywords.append(loc)

    return list(set(keywords)) or ["security", "incident"], topic_hint or None


def main() -> None:
    print("Initialising clients…")
    retriever = Retriever()
    embedder = GeminiEmbedder(settings.gemini_api_key)
    db = SupabaseDB(settings.supabase_url, settings.supabase_service_key)

    try:
        users = db.list_active_profiles()
        print(f"  Loaded {len(users)} user profiles from DB")
    except Exception:
        users = []
        print("  No user profiles found — proceeding without assignment hints")

    total = len(INCIDENTS)
    print(f"\nGenerating workflows for {total} attack types…\n" + "=" * 55)

    results: list[dict] = []
    for i, (key, incident) in enumerate(INCIDENTS.items(), 1):
        label = incident["incident_type"]
        print(f"[{i:02d}/{total}] {label}…", end=" ", flush=True)

        keywords, topic = extract_keywords_and_topic(incident)

        try:
            result = retriever.retrieve(
                RetrievalRequest(
                    keywords=keywords,
                    suspected_attack=topic,
                    k=15,
                    min_similarity=0.25,
                )
            )
        except Exception as e:
            print(f"RETRIEVAL FAILED: {e}")
            results.append({"key": key, "status": "retrieval_error"})
            time.sleep(DELAY_BETWEEN)
            continue

        raw_log = json.dumps(incident, indent=2)
        prompt = build_workflow_prompt(raw_log, result, users)

        try:
            workflow = embedder.generate_json(prompt, model="models/gemini-2.5-flash")
        except Exception as e:
            print(f"GENERATION FAILED: {e}")
            results.append({"key": key, "status": "generation_error"})
            time.sleep(DELAY_BETWEEN)
            continue

        out_path = os.path.join(OUTPUT_DIR, f"{key}.json")
        with open(out_path, "w") as f:
            json.dump(workflow, f, indent=2)

        steps = len(workflow.get("steps", []))
        sev = workflow.get("severity", "?")
        print(f"OK  ({steps} steps, severity={sev})")
        results.append({"key": key, "status": "ok", "steps": steps, "severity": sev})

        if i < total:
            time.sleep(DELAY_BETWEEN)

    print("\n" + "=" * 55 + "\nSUMMARY\n" + "=" * 55)
    ok = [r for r in results if r["status"] == "ok"]
    err = [r for r in results if r["status"] != "ok"]
    for r in results:
        marker = "OK" if r["status"] == "ok" else "FAIL"
        extra = f"  {r.get('steps', '-')} steps  {r.get('severity', '')}" if r["status"] == "ok" else f"  {r['status']}"
        print(f"  [{marker}] {r['key']:<22}{extra}")

    print(f"\n{len(ok)}/{total} succeeded, {len(err)} failed.")
    print(f"Files saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
