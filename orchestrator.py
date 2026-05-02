import json
import subprocess
import os
import requests
from typing import Dict, Any

class SecurityOrchestrator:
    """
    Real-world execution engine for AI-generated workflows.
    Handles 'Easy Fix' security tasks automatically.
    """

    def execute_step(self, step: Dict[str, Any]):
        step_type = step.get("type")
        message = step.get("message")
        params = step.get("params", {})
        integration = step.get("integration", "").lower()

        print(f"\n[ORCHESTRATOR] Processing: {message}")

        if step_type == "APPROVAL":
            print(f"   PAUSED: Waiting for human approval from {step.get('assignedRole')}...")
            input("   Press [ENTER] to simulate approval...")
            return True

        if step_type == "SCRIPT":
            return self._handle_script(step, params)
        
        if step_type == "INTEGRATION":
            return self._handle_integration(step, integration, params)
        
        if step_type == "WEBHOOK":
            return self._handle_webhook(step, params)

        return False

    def _handle_script(self, step: Dict[str, Any], params: Dict[str, Any]):
        print(f"   🚀 EXECUTING AUTOMATED SCRIPT...")
        
        # Example: Enforce local security policy
        if "lockout" in step.get("message", "").lower():
            # Mocking a real system change
            cmd = "echo 'Enforcing account lockout policy...'"
            print(f"   Command: {cmd}")
            subprocess.run(cmd, shell=True)
            return True
        
        # Generic python execution if permitted
        if params.get("language") == "python":
            print(f"   Action: Running Python remediation script...")
            # In a real app, you'd run params.get('code') safely
            return True

        print("   ✓ Script simulated successfully.")
        return True

    def _handle_integration(self, step: Dict[str, Any], integration: str, params: Dict[str, Any]):
        print(f"   🛠️ CONNECTING TO INTEGRATION: {integration.upper()}...")
        
        # Real-world IP Block (Safe Demo Version)
        if "firewall" in integration or "block" in step.get("message", "").lower():
            target_ip = params.get("ip") or params.get("remote_ip") or "203.0.113.42"
            print(f"   Action: Blocking malicious IP {target_ip} on local firewall.")
            
            # Use a safe echo for the demo, but show the real command logic
            if os.uname().sysname == 'Darwin':
                cmd = f"echo 'sudo pfctl -t blocked_ips -T add {target_ip}'"
            else:
                cmd = f"echo 'sudo iptables -A INPUT -s {target_ip} -j DROP'"
                
            subprocess.run(cmd, shell=True)
            print(f"   ✓ IP {target_ip} is now restricted.")
            return True

        print(f"   ✓ Integration {integration} call completed.")
        return True

    def _handle_webhook(self, step: Dict[str, Any], params: Dict[str, Any]):
        print(f"   📡 SENDING WEBHOOK ALERT...")
        target = step.get("target", "General Alert")
        print(f"   Destination: {target}")
        print(f"   Payload: {json.dumps(params)}")
        return True

def run_workflow(file_path: str):
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        return

    with open(file_path, "r") as f:
        workflow = json.load(f)

    print(f"\n" + "="*60)
    print(f"🛡️  AI ORCHESTRATOR STARTING: {workflow.get('title')}")
    print(f"Severity: {workflow.get('severity')} | Playbook: {workflow.get('playbook_id')}")
    print("="*60)

    orchestrator = SecurityOrchestrator()
    for i, step in enumerate(workflow.get("steps", [])):
        print(f"\nSTEP {i+1}/{len(workflow['steps'])}")
        success = orchestrator.execute_step(step)
        if not success:
            print("❌ Step failed. Halting workflow for safety.")
            break
    
    print("\n" + "="*60)
    print("✅ WORKFLOW EXECUTION COMPLETE")
    print("="*60)

if __name__ == "__main__":
    # Test with Brute Force workflow
    target_file = "/Users/tarek/Desktop/HackathoonEmbedder/json_output/brute_force.json"
    run_workflow(target_file)
