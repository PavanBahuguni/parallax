# AutoQA-Reflect: Key Features

> **The Autonomous QA Teammate** - Eliminates manual QA by bridging code changes (PRs), business intent (Jira), and real-world verification across DB → API → UI.

---

## What We've Built

### 1. Semantic Discovery Mapper

**Automatically explores your web application and creates a semantic navigation graph.**

- **Playwright browser automation** crawls the application
- **Network interception** captures which buttons trigger which APIs
- **LLM-powered semantic naming** - components get meaningful names like `column_account_segment` not `button_0`
- **Per-persona graphs** - separate graphs for Reseller, Distributor, Internal users

**Real Output Example:**
```json
{
  "id": "sales_bookings",
  "semantic_name": "sales_bookings",
  "display_header": "Sales Bookings",
  "components": [
    {
      "type": "table_column",
      "role": "column_tcv",
      "selector": "th:has-text('TCV')",
      "triggers_api": ["GET /api/v1/opportunity"]
    }
  ],
  "active_apis": ["POST /graphql", "GET /api/v1/opportunity"]
}
```

---

### 2. Triple-Check Verification (DB → API → UI)

**Verifies data consistency across ALL three layers in a single test run.**

| Layer | What We Check | Example |
|-------|---------------|---------|
| **Database** | Direct PostgreSQL query | `SELECT tcv_amount_uplifted FROM opportunity WHERE id = $1` |
| **API** | Intercept network response | `tcvAmountUplifted: 156723.04` in response |
| **UI** | Playwright DOM assertion | TCV column displays `$156,723.04` |

**Real Bug We Caught:**
```json
{
  "action": "assert_api_field_not_shown",
  "field": "tcvAmount",
  "success": false,
  "error": "SECURITY VIOLATION: 'tcvAmount' found in API response but should be hidden",
  "security_violation": true
}
```

The UI showed the correct uplifted value, but the API was leaking the raw `tcvAmount` that should be hidden from Resellers. UI-only testing would miss this completely.

---

### 3. PR-Diff Intent Mapping

**Analyzes GitHub PRs to understand what changed and generate targeted tests.**

**Input:** Task markdown with PR link
```markdown
# Task: PPT-20
PR: https://github.com/org/repo/pull/948
Verify TCV column displays correctly for each persona
```

**Output:** Mission JSON with test cases, navigation paths, and verification queries
```json
{
  "ticket_id": "PPT-20",
  "target_node": "sales_bookings",
  "personas": ["Reseller", "Distributor"],
  "db_verification": {
    "db_table": "opportunity",
    "db_columns": ["tcv_amount", "tcv_amount_uplifted"]
  },
  "test_cases": [...]
}
```

---

### 4. Persona-Aware Testing

**Tests the same feature from multiple user perspectives automatically.**

| Persona | Login Flow | Data Visibility |
|---------|------------|-----------------|
| Reseller | SSO → CDW partner → Aaron Ferraro | Sees `tcvAmountUplifted`, NOT `tcvAmount` |
| Distributor | SSO → Adistec → Vendor Manager | Sees `tcvAmount` directly |

**Gateway Plan (Reseller):**
```json
{
  "persona": "Reseller",
  "steps": [
    {"action": "click", "selector": "button:has-text('Log In With My Nutanix')"},
    {"action": "fill", "selector": "input[placeholder='Username']", "value": "env(LOGIN_USERNAME)"},
    {"action": "fill", "selector": ".view-as-partner-input", "value": "CDW"},
    {"action": "click", "selector": ".view-as-partner-popup div:has-text('CDW')"}
  ]
}
```

---

### 5. Hybrid Executor (Deterministic + Agentic)

**Fast deterministic execution with LLM fallback for self-healing.**

```
FAST PATH (Deterministic)          HEALER MODE (Agentic)
├── Known selectors                ├── Selector fails
├── Direct Playwright calls   ──▶  ├── LLM analyzes DOM
├── Fast execution                 ├── Finds alternative
                                   └── Records correction
```

---

### 6. Selector Learning

**Records selector corrections for future runs.**

When a selector fails and the LLM finds an alternative:
1. Correction recorded to `SelectorLearner`
2. Mission file updated with working selector
3. Semantic graph component updated
4. Next run uses corrected selector immediately

---

### 7. API Security Verification

**Verifies sensitive fields are NOT exposed in API responses.**

```json
{
  "hidden_api_fields": ["tcvAmount"],
  "verification": {
    "api_field_mapping": {"TCV": "tcvAmountUplifted"}
  }
}
```

If `tcvAmount` appears in the API response for a Reseller, we flag it as a security violation.

---

### 8. Agentic Test Scope Decision

**LLM analyzes PR changes and decides which layers need testing.**

| Change Type | test_db | test_api | test_ui |
|-------------|---------|----------|---------|
| CSS-only | ❌ | ❌ | ✅ |
| New DB column | ✅ | ✅ | ✅ |
| API endpoint change | ❌ | ✅ | ✅ |

---

### 9. Dashboard UI

**React + TypeScript frontend for managing projects, tasks, and viewing results.**

- Project management with persona configuration
- Task execution with real-time log streaming
- Semantic graph visualization
- Execution report viewing

---

## Planned Features

### Jira Integration (In Development)

**Trigger:** Ticket moves to "QA Testing" lane → Webhook fires → Tests run automatically → Results posted back to Jira

### Test Case Approval Workflow (Planned)

**Flow:** PR analyzed → Test cases generated → Human reviews → Approved tests executed

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Browser Automation | Playwright, browser-use |
| LLM | Nutanix GPT-120B, Ollama |
| Vector Storage | ChromaDB |
| Graph Storage | NetworkX, JSON |
| Database | PostgreSQL, asyncpg |
| GitHub Integration | PyGithub, httpx |
| Frontend | React, TypeScript, Vite |
| Backend | FastAPI |

---

## Competitive Edge

| Feature | AutoQA-Reflect | Traditional Tools |
|---------|----------------|-------------------|
| DB verification | ✅ Direct SQL | ❌ |
| API verification | ✅ Intercepted | ⚠️ Manual |
| PR-driven testing | ✅ Automatic | ❌ |
| Self-healing | ✅ LLM + Learning | ❌ |
| Multi-persona | ✅ Native | ❌ Manual |
| Security checks | ✅ Hidden field detection | ❌ |

---

## One-Line Summary

> **"Triple-check verification: because 'it shows on the UI' doesn't mean the database is correct."**
