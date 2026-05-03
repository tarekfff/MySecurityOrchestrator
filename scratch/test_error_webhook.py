"""
Test that /analyze fires the error webhook for both failure modes:
  1. Successful analysis (happy path — should NOT send error payload)
  2. Force workflow-generation failure by temporarily breaking the endpoint
     (we test this by patching settings inside the process)

Strategy:
  - Start a tiny HTTP server on port 9997 to catch webhooks
  - Patch settings.friend_webhook_url to http://localhost:9997
  - Call the analyze functions directly (no HTTP round-trip needed)
  - Print what the catcher received
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch, AsyncMock

# ── Webhook catcher ────────────────────────────────────────────────────────────

received_payloads: list[dict] = []

class _CatcherHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            received_payloads.append(json.loads(body))
        except Exception:
            received_payloads.append({"raw": body.decode()})
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_):
        pass  # silence default access log

def _start_catcher(port=9997):
    srv = HTTPServer(("127.0.0.1", port), _CatcherHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv

# ── Tests ──────────────────────────────────────────────────────────────────────

WEBHOOK_URL = "http://127.0.0.1:9997"

# Sample incident payloads
WAZUH_INCIDENT = {
    "rule": {
        "level": 10,
        "description": "sshd: Multiple authentication failures",
        "mitre": {"id": ["T1110.003"], "tactic": ["Credential Access"]},
    },
    "data": {"srcip": "203.0.113.42", "dstuser": "root"},
    "alert": {"severity": "HIGH", "category": "brute_force"},
}

MANUAL_INCIDENT = {
    "incident_type": "SQL Injection",
    "description": "Customer reported ' OR 1=1 appearing in error logs.",
}


async def run_tests():
    import sys
    sys.path.insert(0, "/Users/tarek/Desktop/HackathoonEmbedder")

    from config import settings
    from fastapi import BackgroundTasks

    print("=" * 60)
    print("Starting webhook catcher on", WEBHOOK_URL)
    print("=" * 60)
    _start_catcher(9997)

    # Patch the webhook URL for this test run
    with patch.object(settings, "friend_webhook_url", WEBHOOK_URL):

        # ── Test 1: retrieval failure (embedding service throws) ──────────────
        print("\n[TEST 1] Simulating retrieval/embedding failure...")
        received_payloads.clear()

        from api import analyze, _get_retriever
        from retriever import Retriever

        def _boom(*_, **__):
            raise RuntimeError("Simulated rate-limit / embedding failure")

        with patch.object(Retriever, "retrieve", side_effect=_boom):
            bt = BackgroundTasks()
            resp = await analyze(WAZUH_INCIDENT, bt)
            # Run the background tasks (webhook send) synchronously
            for task in bt.tasks:
                await task()

        if received_payloads:
            p = received_payloads[0]
            print("  ✅  Webhook received!")
            print(f"     error        : {p.get('error')}")
            print(f"     incident_type: {p.get('incident_type')}")
            print(f"     summary      : {p.get('summary')}")
            print(f"     workflow     : {p.get('workflow')}")
        else:
            print("  ❌  No webhook received — check FRIEND_WEBHOOK_URL config")

        # ── Test 2: workflow generation failure ───────────────────────────────
        print("\n[TEST 2] Simulating workflow generation failure...")
        received_payloads.clear()

        from embedder import GeminiEmbedder

        def _gen_boom(*_, **__):
            raise RuntimeError("Simulated Gemini timeout during workflow generation")

        with patch.object(GeminiEmbedder, "generate_json", side_effect=_gen_boom):
            bt = BackgroundTasks()
            resp = await analyze(MANUAL_INCIDENT, bt)
            for task in bt.tasks:
                await task()

        if received_payloads:
            p = received_payloads[0]
            print("  ✅  Webhook received!")
            print(f"     error        : {p.get('error')}")
            print(f"     incident_type: {p.get('incident_type')}")
            print(f"     summary      : {p.get('summary')}")
            print(f"     workflow     : {p.get('workflow')}")
        else:
            print("  ❌  No webhook received — check FRIEND_WEBHOOK_URL config")

        # ── Test 3: happy path — successful workflow (NOT an error webhook) ───
        print("\n[TEST 3] Happy path — successful analysis (no error webhook expected)...")
        received_payloads.clear()

        bt = BackgroundTasks()
        resp = await analyze(WAZUH_INCIDENT, bt)
        for task in bt.tasks:
            await task()

        if received_payloads:
            p = received_payloads[0]
            is_error = p.get("error", False)
            if is_error:
                print("  ⚠️  Received an error webhook on the happy path — unexpected")
            else:
                print("  ✅  Webhook received (successful workflow, not an error)")
                print(f"     title   : {p.get('title', '(no title — raw workflow)')}")
                print(f"     severity: {p.get('severity')}")
                print(f"     steps   : {len(p.get('steps', []))} step(s)")
        else:
            print("  ⚠️  No webhook received on happy path (workflow may be None or URL not set)")

    print("\n" + "=" * 60)
    print("All tests complete.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
