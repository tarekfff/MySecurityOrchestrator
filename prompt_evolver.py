import json
import os
import time
from typing import List, Dict, Any
from google.genai import types
from embedder import GeminiEmbedder
from config import settings
from retriever import Retriever, RetrievalRequest
from db import SupabaseDB

# Constants for evaluation
ALLOWED_ROLES = ["SOC_ANALYST", "SOC_LEAD", "CISO", "IT_ADMIN", "LEGAL", "EXEC", "ADMIN"]
ALLOWED_TYPES = ["APPROVAL", "INTEGRATION", "WEBHOOK", "SCRIPT"]

# Benchmark Incident
TEST_INCIDENT = {
    "incident_type": "SQL Injection",
    "description": "Detected ' UNION SELECT NULL, username, password FROM users-- in the search field.",
    "alert": {"category": "sql_injection"}
}

# Prompt Candidates
PROMPT_CANDIDATES = [
    # Candidate 0: The Current Prompt (Baseline)
    """You are a Cyber-Automation Architect. 
    Generate a valid JSON workflow based on the incident and KB.
    Use the provided user profiles and roles correctly.""",

    # Candidate 1: More detailed, instruction-heavy
    """You are an Expert Incident Response Engineer. 
    Your goal is to produce a HIGH-PRECISION JSON workflow.
    Rules:
    1. Every step must have a clear 'message' derived from the Knowledge Base.
    2. Assign tasks to specific users (UUID) ONLY if their skills match the task perfectly.
    3. Use 'IT_ADMIN' for system changes and 'SOC_ANALYST' for investigation.
    4. Return ONLY the JSON object.""",

    # Candidate 2: Focus on WAHH logic and mitigation
    """You are the Lead Security Orchestrator.
    Using the Web Application Hacker's Handbook (WAHH) principles found in the KB:
    1. Create a multi-step workflow starting with containment.
    2. Ensure severity is correctly mapped (SQLi is usually HIGH/CRITICAL).
    3. If 'coding' skills are needed, find a user with those skills.
    4. Output strictly valid JSON."""
]

class PromptEvolver:
    def __init__(self):
        self.embedder = GeminiEmbedder(settings.gemini_api_key)
        self.retriever = Retriever()
        self.db = SupabaseDB(settings.supabase_url, settings.supabase_service_key)
        self.users = self.db.list_active_profiles()

    def evaluate_output(self, output: Any) -> float:
        """Calculate an accuracy score from 0.0 to 10.0"""
        if isinstance(output, list) and len(output) > 0:
            output = output[0]
            
        if not isinstance(output, dict):
            return 0.0

        score = 0.0
        
        # 1. Basic Structure (2.0 pts)
        if all(k in output for k in ["source", "severity", "title", "steps"]):
            score += 2.0
        
        # 2. Steps Validity (3.0 pts)
        steps = output.get("steps", [])
        if steps:
            valid_steps = 0
            for s in steps:
                if s.get("type") in ALLOWED_TYPES and s.get("assignedRole") in ALLOWED_ROLES:
                    valid_steps += 1
            score += (valid_steps / len(steps)) * 3.0
        
        # 3. Content Quality (3.0 pts)
        # Check if messages are descriptive (length > 20)
        long_messages = sum(1 for s in steps if len(s.get("message", "")) > 40)
        if steps:
            score += (long_messages / len(steps)) * 3.0
            
        # 4. Intelligence Check (2.0 pts)
        # Did it actually use a UUID for a user?
        has_uuids = any(s.get("assignedUser") is not None for s in steps)
        if has_uuids:
            score += 2.0
            
        return round(score, 2)

    def run_evolution(self):
        print("🧬 Starting Prompt Evolution System\n" + "="*50)
        
        # Get Context once for the benchmark
        keywords = ["sql_injection", "union", "select"]
        context_result = self.retriever.retrieve(RetrievalRequest(keywords=keywords, suspected_attack="sql_injection"))
        
        best_score = -1.0
        best_prompt = ""
        results = []

        for i, candidate in enumerate(PROMPT_CANDIDATES):
            print(f"Testing Candidate {i}...", end=" ", flush=True)
            
            # Construct the full prompt
            full_prompt = f"""{candidate}
            
            Available Users: {json.dumps(self.users)}
            Context: {context_result.assembled_context}
            Incident: {json.dumps(TEST_INCIDENT)}
            
            JSON Output:"""

            try:
                # Generate
                start_time = time.time()
                output_json = self.embedder.generate_json(full_prompt)
                elapsed = time.time() - start_time
                
                # Evaluate
                score = self.evaluate_output(output_json)
                print(f"DONE (Score: {score}/10.0, {elapsed:.1f}s)")
                
                results.append({
                    "id": i,
                    "score": score,
                    "prompt": candidate,
                    "output": output_json
                })
                
                if score > best_score:
                    best_score = score
                    best_prompt = candidate

            except Exception as e:
                print(f"FAILED: {e}")
            
            time.sleep(2) # Respect RPM

        print("\n" + "="*50 + "\n🏆 EVOLUTION SUMMARY\n" + "="*50)
        for res in results:
            medal = "⭐" if res["score"] == best_score else "  "
            print(f"{medal} Candidate {res['id']}: {res['score']}/10.0")

        print(f"\n✅ Best Prompt Chosen:\n{best_prompt}")
        
        # Save best prompt for future use
        with open("best_prompt.txt", "w") as f:
            f.write(best_prompt)

if __name__ == "__main__":
    evolver = PromptEvolver()
    evolver.run_evolution()
