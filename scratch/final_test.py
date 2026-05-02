import requests
import json

# Sample Brute Force incident (Wazuh format)
incident = {
  "rule": {
    "level": 10,
    "description": "sshd: Multiple authentication failures from same source - Brute force attack",
    "id": "5712",
    "mitre": {
      "id": ["T1110.003"],
      "tactic": ["Credential Access"],
      "technique": ["Password Spraying"]
    }
  },
  "agent": {
    "id": "003",
    "name": "web-server-01",
    "ip": "10.0.1.50"
  },
  "data": {
    "srcip": "203.0.113.42",
    "dstuser": "root"
  },
  "alert": {
    "severity": "HIGH",
    "category": "brute_force",
    "playbook": "brute_force",
    "incident_type": "Brute Force Attack"
  },
  "timestamp": "2026-05-02T03:25:33.000+0000",
  "location": "/var/log/auth.log"
}

def test_api():
    url = "http://0.0.0.0:8000/analyze"
    print(f"Testing {url} ...")
    try:
        response = requests.post(url, json=incident)
        if response.status_code == 200:
            data = response.json()
            print("\n✅ Analysis Successful!")
            print(f"Incident Type: {data['incident_type']}")
            
            print("\n--- Generated Workflow JSON ---")
            if data.get('workflow'):
                print(json.dumps(data['workflow'], indent=2))
            else:
                print("No workflow generated.")
                
            print("\n--- LLM Prompt (Analysis) Preview ---")
            prompt = data['retrieval'].get('llm_prompt')
            if prompt:
                print(prompt[:200] + "...")
            else:
                print("No prompt generated.")
            
        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    test_api()
