# AutoQA-Reflect: How It Works

## The Problem

Traditional testing only verifies the UI layer:

| What Tests Check | What Can Go Wrong |
|------------------|-------------------|
| "Button shows success" | DB write failed silently |
| "UI displays $156K" | Wrong value from API |
| "Page loads fine" | API leaks sensitive data |

**Real Bug We Caught:**
- UI shows TCV = $156,723 (correct for Reseller)
- But API also returns `tcvAmount = $152,021` (should be hidden)
- Security vulnerability invisible to UI testing

---

## Our Solution: Triple-Check Verification

```
1. DATABASE    SELECT tcv_amount_uplifted FROM opportunity WHERE id = $1
               ✅ Result: 156723.04

2. API         GET /api/v1/opportunity
               ✅ tcvAmountUplifted: 156723.04
               ❌ ALSO contains tcvAmount: 152021.35 (should be hidden!)

3. UI          TCV Column displays: $156,723
               ✅ Correct value shown

RESULT: ❌ SECURITY VIOLATION - Hidden field exposed in API
```

---

## The Three Phases

### Phase 1: Discovery (Semantic Mapper)

Crawls your application and builds a semantic navigation graph:

```json
{
  "nodes": [{
    "id": "sales_bookings",
    "components": [
      {"role": "column_tcv", "selector": "th:has-text('TCV')", "triggers_api": ["GET /api/v1/opportunity"]}
    ],
    "active_apis": ["POST /graphql", "GET /api/v1/opportunity"]
  }],
  "edges": [{"from": "dashboard", "to": "sales_bookings", "selector": "a[href='/sales/data/bookings']"}]
}
```

### Phase 2: Intent Processing (Context Processor)

Takes a task + PR link and generates a mission:

**Input:**
```markdown
# Task: PPT-20
PR: https://github.com/org/repo/pull/948
Verify TCV column for Reseller and Distributor
```

**Output:**
```json
{
  "ticket_id": "PPT-20",
  "personas": ["Reseller", "Distributor"],
  "test_cases": [{
    "id": "verify_tcv_reseller",
    "hidden_api_fields": ["tcvAmount"]
  }],
  "db_verification": {
    "db_table": "opportunity",
    "db_columns": ["tcv_amount", "tcv_amount_uplifted"]
  }
}
```

### Phase 3: Execution (Triple-Check Executor)

For each persona:
1. **Gateway Login** - SSO with persona-specific partner selection
2. **Navigation** - Follow semantic graph to target page
3. **Triple Verification** - DB query, API intercept, UI assert
4. **Security Checks** - Verify hidden fields not exposed

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Browser | Playwright, browser-use |
| LLM | Nutanix GPT-120B, Ollama |
| Vector DB | ChromaDB |
| Database | PostgreSQL, asyncpg |
| Frontend | React, TypeScript, Vite |
| Backend | FastAPI |

---

## Key Differentiators

1. **Full-Stack Verification** - DB, API, and UI in one test
2. **PR-Driven** - Tests generated from actual code changes
3. **Persona-Aware** - Different expectations per user role
4. **Security Checks** - Catches API data leaks
5. **Self-Healing** - LLM fixes broken selectors

---

## Planned: Jira Integration

```
Ticket moves to "QA Testing"
         │
         ▼
Jira webhook fires
         │
         ▼
Tests run automatically
         │
         ▼
Results posted to ticket
```

---

## Tagline

> **"Triple-check verification: because 'it shows on the UI' doesn't mean the database is correct."**
