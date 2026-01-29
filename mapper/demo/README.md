# AutoQA-Reflect Demo Materials

Demo materials for **AutoQA-Reflect** - the Autonomous QA Teammate.

## Contents

| File | Description |
|------|-------------|
| [KEY_FEATURES.md](./KEY_FEATURES.md) | All features we've built with examples |
| [DEMO_SCRIPT.md](./DEMO_SCRIPT.md) | Step-by-step demo walkthrough |
| [SOLUTION_OVERVIEW.md](./SOLUTION_OVERVIEW.md) | Architecture and how it works |
| [JIRA_INTEGRATION_FLOW.md](./JIRA_INTEGRATION_FLOW.md) | Planned Jira integration |
| [sample_mission.json](./sample_mission.json) | Example mission file |
| [sample_report.json](./sample_report.json) | Example execution report |
| [sample_semantic_graph.json](./sample_semantic_graph.json) | Example semantic graph |

---

## Quick Start

```bash
# Terminal 1: Backend
cd mapper/backend
uv run uvicorn app.main:app --reload --port 8001

# Terminal 2: Frontend  
cd mapper/frontend
npm run dev

# Access dashboard at http://localhost:5173
```

---

## Key Demo Points

### 1. Triple-Check Verification
- **Database**: `SELECT tcv_amount_uplifted FROM opportunity WHERE id = $1`
- **API**: Intercept network response, verify `tcvAmountUplifted: 156723.04`
- **UI**: Assert TCV column displays `$156,723.04`

### 2. Security Bug Found
```json
{
  "error": "SECURITY VIOLATION: 'tcvAmount' found in API response but should be hidden",
  "security_violation": true
}
```

### 3. Persona-Aware Testing
- Reseller sees `tcvAmountUplifted`
- Distributor sees `tcvAmount`
- Same test, different expectations per role

---

## Tagline

> **"Triple-check verification: because 'it shows on the UI' doesn't mean the database is correct."**
