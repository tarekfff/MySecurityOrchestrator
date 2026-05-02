import requests
import json
import time
import os

API_URL = "http://0.0.0.0:8000/analyze"
OUTPUT_DIR = "/Users/tarek/Desktop/HackathoonEmbedder/json_output"

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Comprehensive list of incidents for testing
INCIDENTS = {
    "xss": {
        "incident_type": "Cross-Site Scripting (XSS)",
        "alert": {"category": "xss"},
        "description": "Detected <script>alert(1)</script> in the search query parameter.",
        "location": "https://example.com/search?q=<script>alert(1)</script>"
    },
    "sql_injection": {
        "incident_type": "SQL Injection",
        "alert": {"category": "sql_injection"},
        "description": "Detected ' OR '1'='1 in the login form username field.",
        "data": {"dstuser": "' OR '1'='1"}
    },
    "csrf": {
        "incident_type": "CSRF",
        "alert": {"category": "csrf"},
        "description": "State-changing request received without a valid anti-CSRF token.",
        "location": "/api/v1/user/update_email"
    },
    "rce": {
        "incident_type": "Remote Code Execution",
        "alert": {"category": "rce"},
        "description": "Attempted OS command injection via shell metacharacters: ; cat /etc/passwd",
        "data": {"payload": "; cat /etc/passwd"}
    },
    "path_traversal": {
        "incident_type": "Path Traversal",
        "alert": {"category": "path_traversal"},
        "description": "Access attempt to sensitive file using ../../etc/shadow",
        "location": "/download?file=../../etc/shadow"
    },
    "brute_force": {
        "incident_type": "Brute Force",
        "alert": {"category": "brute_force"},
        "description": "Multiple failed login attempts for user 'admin' from IP 203.0.113.42",
        "data": {"srcip": "203.0.113.42", "dstuser": "admin"}
    },
    "phishing": {
        "incident_type": "Phishing",
        "alert": {"category": "phishing"},
        "description": "User reported a suspicious email from 'it-support-portal.net' requesting password reset.",
        "data": {"domain": "it-support-portal.net"}
    },
    "ransomware": {
        "incident_type": "Ransomware",
        "alert": {"category": "ransomware"},
        "description": "Mass file encryption detected on FileServer-01. Extension changed to .locked",
        "data": {"host": "FileServer-01", "extension": ".locked"}
    },
    "data_breach": {
        "incident_type": "Data Breach",
        "alert": {"category": "data_breach"},
        "description": "Unusually high data exfiltration to external IP 45.33.12.98 detected by DLP.",
        "data": {"dest_ip": "45.33.12.98", "volume": "5GB"}
    },
    "ddos": {
        "incident_type": "DDoS",
        "alert": {"category": "ddos"},
        "description": "Traffic spike detected: 100,000 requests/sec from 500 different IPs.",
        "data": {"rps": 100000}
    },
    "session_management": {
        "incident_type": "Session Management Flaw",
        "alert": {"category": "session_management"},
        "description": "Session fixation attempt: application accepted a user-provided session ID.",
        "data": {"session_id": "FIXED_ID_123"}
    },
    "access_control": {
        "incident_type": "Access Control Violation (IDOR)",
        "alert": {"category": "access_control"},
        "description": "User A attempted to access User B's profile via direct ID manipulation.",
        "location": "/user/profile/5001"
    },
    "xxe": {
        "incident_type": "XML External Entity (XXE)",
        "alert": {"category": "xxe"},
        "description": "XML upload contains an external entity reference to /etc/hostname",
        "data": {"payload": "<!ENTITY xxe SYSTEM 'file:///etc/hostname'>"}
    },
    "ssrf": {
        "incident_type": "SSRF",
        "alert": {"category": "ssrf"},
        "description": "Request to internal metadata service from the application server.",
        "location": "http://169.254.169.254/latest/meta-data/"
    },
    "clickjacking": {
        "incident_type": "Clickjacking",
        "alert": {"category": "clickjacking"},
        "description": "Security audit found X-Frame-Options header missing on critical pages.",
        "location": "/payments/checkout"
    },
    "open_redirect": {
        "incident_type": "Open Redirect",
        "alert": {"category": "open_redirect"},
        "description": "Unvalidated redirect found in the login redirection parameter.",
        "location": "/login?redirect=http://attacker.com"
    },
    "file_upload": {
        "incident_type": "Unrestricted File Upload",
        "alert": {"category": "file_upload"},
        "description": "PHP web shell uploaded as shell.php.jpg",
        "data": {"filename": "shell.php.jpg"}
    },
    "deserialization": {
        "incident_type": "Insecure Deserialization",
        "alert": {"category": "deserialization"},
        "description": "Suspicious Java serialized object detected in the 'JSESSIONID' cookie.",
        "data": {"cookie": "rO0ABXNyA..."}
    },
    "business_logic": {
        "incident_type": "Business Logic Flaw",
        "alert": {"category": "business_logic"},
        "description": "Negative price used in the shopping cart checkout process.",
        "data": {"price": -100.0}
    }
}

def run_tests():
    print(f"🚀 Starting Attack Analysis Test Suite. Saving to {OUTPUT_DIR}\n" + "="*50)
    
    results = []
    for key, incident in INCIDENTS.items():
        print(f"Testing: {incident['incident_type']}...", end=" ", flush=True)
        try:
            # We add a custom instruction to the log to ensure AI knows we want ONLY json
            # although the API already enforces this via response_mime_type.
            response = requests.post(API_URL, json=incident, timeout=45)
            
            if response.status_code == 200:
                data = response.json()
                workflow = data.get("workflow")
                
                if workflow:
                    # Save the workflow JSON to a file
                    file_path = os.path.join(OUTPUT_DIR, f"{key}.json")
                    with open(file_path, "w") as f:
                        json.dump(workflow, f, indent=2)
                    
                    status = "✅ SAVED"
                    chunks = data.get("retrieval", {}).get("chunks_found", 0)
                    print(f"{status} ({chunks} chunks)")
                else:
                    status = "⚠️ NO WORKFLOW"
                    print(status)
                
                results.append({"topic": key, "status": status})
            else:
                print(f"❌ ERROR {response.status_code}")
        except Exception as e:
            print(f"❌ FAILED: {e}")
        
        # Delay to respect free tier rate limits (RPM)
        time.sleep(3.0)

    print("\n" + "="*50 + "\n📊 TEST SUMMARY\n" + "="*50)
    for res in results:
        print(f"{res['topic']:<20} | {res['status']}")

if __name__ == "__main__":
    run_tests()
