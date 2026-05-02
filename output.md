# Workflow Payload Reference

Send a `POST` request to `/api/workflow/execute` with the header:

```
x-workflow-secret: <WORKFLOW_WEBHOOK_SECRET from .env>
Content-Type: application/json
```

---

## Top-level structure

```json
{
  "source":           "string  (required) — origin system name",
  "severity":         "LOW | MEDIUM | HIGH | CRITICAL  (required)",
  "title":            "string  (required) — human-readable incident title",
  "playbook_id":      "string  (optional) — e.g. PB-RANSOMWARE-001",
  "playbook_version": "string  (optional) — e.g. 2.1",
  "ai_confidence":    "number  (optional) — 0.0 to 1.0",
  "steps":            [ ...step objects... ]
}
```

---

## Step types

Every step shares these common fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `APPROVAL \| INTEGRATION \| WEBHOOK \| SCRIPT` | Yes | Step type |
| `assignedRole` | `SOC_ANALYST \| SOC_LEAD \| CISO \| IT_ADMIN \| LEGAL \| EXEC \| ADMIN` | No | Role that receives the task/notification |
| `assignedUser` | UUID string | No | Specific user ID (overrides role) |
| `message` | string | No | Instructions shown to the assignee |
| `priorityLevel` | `LOW \| MEDIUM \| HIGH \| CRITICAL` | No | Defaults to `MEDIUM` |
| `scheduledTime` | ISO 8601 datetime | No | Delay execution until this time |

> **Notifications are automatic.** Every step notifies its `assignedUser` or all users with `assignedRole` via email (if `notify_email = true` on their profile). You do not need a separate EMAIL/SMS step.

> **SLA is automatic for APPROVAL steps.** Deadline is calculated from incident severity at the moment the step starts: CRITICAL = 1 h, HIGH = 4 h, MEDIUM = 24 h, LOW = 72 h.

---

### `APPROVAL`

Pauses the workflow and waits for a human decision (approve / reject / report).

```json
{
  "type": "APPROVAL",
  "assignedRole": "SOC_LEAD",
  "message": "Approve shutting down the Finance VLAN. This will affect 47 users.",
  "priorityLevel": "CRITICAL"
}
```

Assign to a specific user instead of a role:

```json
{
  "type": "APPROVAL",
  "assignedUser": "550e8400-e29b-41d4-a716-446655440000",
  "message": "CISO sign-off required before contacting law enforcement."
}
```

---

### `SCRIPT`

Automated step — runs a script or triggers an internal action. Executes immediately, no human input needed.

```json
{
  "type": "SCRIPT",
  "assignedRole": "IT_ADMIN",
  "message": "Run host-isolation.sh on FIN-SRV-01, FIN-SRV-02, FIN-SRV-03."
}
```

---

### `INTEGRATION`

Calls an external system (SIEM, CMDB, EDR, etc.).

| Extra field | Type | Description |
|-------------|------|-------------|
| `integration` | string | System name — e.g. `splunk`, `servicenow`, `veeam`, `crowdstrike` |
| `target` | string | Resource or query target |
| `params` | object | Arbitrary key-value parameters passed to the integration |

```json
{
  "type": "INTEGRATION",
  "integration": "splunk",
  "target": "index=firewall src_ip=185.220.101.47",
  "params": {
    "timerange": "-24h",
    "limit": 1000
  },
  "assignedRole": "SOC_ANALYST",
  "message": "Pull all firewall logs for the exfiltration IP."
}
```

---

### `WEBHOOK`

Sends an HTTP callback to an external URL.

| Extra field | Type | Description |
|-------------|------|-------------|
| `target` | string | Destination URL |
| `params` | object | Payload forwarded to the webhook |

```json
{
  "type": "WEBHOOK",
  "target": "https://internal-ticketing.corp/api/incidents",
  "params": {
    "priority": "P1",
    "team": "infrastructure"
  },
  "message": "Open a P1 ticket in the internal ticketing system."
}
```

---

## Complete examples

### Example 1 — Ransomware response (4 steps)

```json
{
  "source": "EDR — CrowdStrike",
  "severity": "CRITICAL",
  "title": "Ransomware Detected on Finance Servers",
  "playbook_id": "PB-RANSOMWARE-001",
  "playbook_version": "3.0",
  "ai_confidence": 0.97,
  "steps": [
    {
      "type": "SCRIPT",
      "assignedRole": "SOC_ANALYST",
      "message": "Execute host-isolation script on FIN-SRV-01, FIN-SRV-02, FIN-SRV-03.",
      "priorityLevel": "CRITICAL"
    },
    {
      "type": "INTEGRATION",
      "integration": "veeam",
      "target": "backup-job/finance-servers",
      "message": "Trigger emergency snapshot of Finance servers before remediation.",
      "assignedRole": "IT_ADMIN",
      "priorityLevel": "CRITICAL"
    },
    {
      "type": "APPROVAL",
      "assignedRole": "SOC_LEAD",
      "message": "Approve full Finance VLAN shutdown. This will impact 47 users.",
      "priorityLevel": "CRITICAL"
    },
    {
      "type": "APPROVAL",
      "assignedRole": "CISO",
      "message": "CISO authorization required before notifying law enforcement (DGSN).",
      "priorityLevel": "CRITICAL"
    }
  ]
}
```

---

### Example 2 — Data breach / Law 18-07 compliance (5 steps)

```json
{
  "source": "DLP — Symantec",
  "severity": "CRITICAL",
  "title": "Customer PII Data Exfiltration — Law 18-07 Breach",
  "playbook_id": "PB-DATA-BREACH-001",
  "ai_confidence": 0.92,
  "steps": [
    {
      "type": "SCRIPT",
      "assignedRole": "SOC_ANALYST",
      "message": "Terminate network connection to 185.220.101.47 and update firewall rules.",
      "priorityLevel": "CRITICAL"
    },
    {
      "type": "INTEGRATION",
      "integration": "splunk",
      "target": "index=dlp dest_ip=185.220.101.47",
      "params": { "timerange": "-7d" },
      "assignedRole": "IT_ADMIN",
      "message": "Pull full exfiltration log from SIEM for the past 7 days."
    },
    {
      "type": "APPROVAL",
      "assignedRole": "SOC_LEAD",
      "message": "Approve notification to ANPDP (data protection authority) within the 72h Law 18-07 window."
    },
    {
      "type": "APPROVAL",
      "assignedRole": "LEGAL",
      "message": "Legal review of breach notification letter. Confirm Law 18-07 Art. 26 compliance wording."
    },
    {
      "type": "APPROVAL",
      "assignedRole": "CISO",
      "message": "Final CISO sign-off on breach report before submission to ANPDP."
    }
  ]
}
```

---

### Example 3 — Phishing campaign (3 steps)

```json
{
  "source": "Email Gateway — Proofpoint",
  "severity": "HIGH",
  "title": "Targeted Spear-Phishing — C-Suite Executives",
  "ai_confidence": 0.88,
  "steps": [
    {
      "type": "APPROVAL",
      "assignedRole": "SOC_ANALYST",
      "message": "Block domain 'secure-login-portal[.]com' and all subdomains at perimeter."
    },
    {
      "type": "APPROVAL",
      "assignedRole": "IT_ADMIN",
      "message": "Force password reset on all accounts that clicked the phishing link."
    },
    {
      "type": "APPROVAL",
      "assignedRole": "CISO",
      "message": "Approve executive awareness communication to be sent by the security team."
    }
  ]
}
```

---

### Example 4 — Low severity, scheduled follow-up

```json
{
  "source": "Firewall — pfSense",
  "severity": "LOW",
  "title": "Repeated Port Scan from 203.0.113.42",
  "ai_confidence": 0.61,
  "steps": [
    {
      "type": "APPROVAL",
      "assignedRole": "SOC_ANALYST",
      "message": "Confirm if 203.0.113.42 is a known scanner. If not, add to blocklist.",
      "priorityLevel": "LOW"
    },
    {
      "type": "WEBHOOK",
      "target": "https://internal-ticketing.corp/api/incidents",
      "params": { "priority": "P4", "team": "network" },
      "message": "Open a low-priority ticket for network team follow-up.",
      "scheduledTime": "2026-05-03T08:00:00Z"
    }
  ]
}
```

---

## Severity → automatic SLA (APPROVAL steps only)

| Severity | SLA deadline |
|----------|-------------|
| `CRITICAL` | 1 hour |
| `HIGH` | 4 hours |
| `MEDIUM` | 24 hours |
| `LOW` | 72 hours |

---

## Role → who sees the task in the dashboard

| `assignedRole` | Who gets the task |
|----------------|------------------|
| `SOC_ANALYST` | Any active SOC Analyst |
| `SOC_LEAD` | Any active SOC Lead (and above) |
| `IT_ADMIN` | Any active IT Admin |
| `LEGAL` | Any active Legal user |
| `CISO` | CISO |
| `EXEC` | Executive |
| `ADMIN` | Platform Admin |

When `assignedUser` is set it takes precedence — only that specific user sees the task.

---

## Validation errors

If the payload is invalid, the API returns `400` with details:

```json
{
  "error": "Invalid workflow payload",
  "details": {
    "steps": {
      "0": {
        "type": {
          "_errors": ["Invalid enum value. Expected 'APPROVAL' | 'INTEGRATION' | 'WEBHOOK' | 'SCRIPT'"]
        }
      }
    }
  }
}
```

On success the API returns `202`:

```json
{
  "message": "Workflow Accepted",
  "incidentId": "550e8400-e29b-41d4-a716-446655440000"
}
```