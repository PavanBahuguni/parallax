# AutoQA-Reflect Demo Script

## Demo Overview

**Duration:** 10-15 minutes  
**Goal:** Demonstrate how AutoQA-Reflect autonomously tests web applications using PR-intent mapping and triple-check verification.

---

## Setup Requirements

### Prerequisites
- AutoQA-Reflect backend running on port 8001
- Frontend dashboard running on port 5173
- Target application (Partner Central) running on port 9000
- PostgreSQL database with test data
- Environment variables configured (`.env` file)

### Quick Start Commands
```bash
# Terminal 1: Start Backend
cd mapper/backend
uv run uvicorn app.main:app --reload --port 8001

# Terminal 2: Start Frontend
cd mapper/frontend
npm run dev

# Terminal 3: Target App (Partner Central)
# (Your application should be running on localhost:9000)
```

---

## Demo Flow

### Act 1: The Problem (2 minutes)

**Narration:**
> "Today's enterprise applications are complex multi-layered systems. A single feature involves:
> - Frontend React components
> - Backend API endpoints
> - Database tables
> - Different user personas with different permissions
>
> Traditional testing tools only verify what the user SEES. But bugs hide in the layers beneath.
>
> Let me show you a real example..."

**Show Example Bug:**
```
A developer adds a new TCV column to the Sales Bookings page.
- UI shows the column ✅
- But Resellers shouldn't see the raw tcvAmount—only tcvAmountUplifted
- Traditional tests pass because UI looks correct
- Security vulnerability goes unnoticed
```

---

### Act 2: Discovery Phase - Building the Digital Twin (3 minutes)

**Action:** Navigate to the Projects page in the dashboard.

**Narration:**
> "AutoQA-Reflect starts by building a 'Digital Twin' of your application—a semantic navigation graph that maps every page, component, and their relationships."

**Demo Steps:**

1. **Show the Semantic Graph Viewer**
   - Open Project Detail Page
   - Click on "View Semantic Graph"
   - Show the graph visualization

2. **Explain the Graph Structure:**
   ```
   "Each node represents a page state:
   - partner_dashboard (home page)
   - sales_bookings (data table view)
   - sales_bookings_page (filtered view)
   
   Edges show how to navigate between them."
   ```

3. **Deep Dive into a Node:**
   ```json
   {
     "id": "sales_bookings",
     "description": "Sales data dashboard with opportunity table",
     "components": [
       {
         "role": "column_tcv",
         "selector": "th:has-text('TCV')",
         "triggers_api": ["GET /api/v1/opportunity"]
       }
     ],
     "active_apis": ["POST /graphql", "GET /api/v1/opportunity"]
   }
   ```

4. **Highlight Key Points:**
   - Semantic names (not `button_0` but `column_account_segment`)
   - API anchoring (which buttons trigger which endpoints)
   - Multi-persona support (separate graphs for Reseller, Distributor)

---

### Act 3: Intent Processing - From Jira to Test Plan (3 minutes)

**Narration:**
> "When a Jira ticket moves to QA lane, AutoQA-Reflect automatically:
> 1. Reads the ticket description
> 2. Fetches the linked PR
> 3. Analyzes the code changes
> 4. Generates targeted test cases"

**Show Task File:**
```markdown
# Task: PPT-20 - Verify TCV Column Display

## Description
Verify that the TCV column displays the correct value based on user role:
- Resellers see tcvAmountUplifted (and tcvAmount is hidden)
- Distributors see tcvAmount

## PR Link
https://github.com/nutanix-saas-engineering/partner-app/pull/948
```

**Show Generated Mission:**
```json
{
  "ticket_id": "PPT-20",
  "target_node": "new_logo_bookings",
  "personas": ["Reseller", "Distributor"],
  "intent": {
    "primary_entity": "Opportunity",
    "changes": [
      "Added TCV column to Opportunity view",
      "Conditional display: tcvAmountUplifted for Resellers",
      "Conditional display: tcvAmount for Distributors"
    ]
  },
  "db_verification": {
    "db_table": "opportunity",
    "db_columns": ["tcv_amount", "tcv_amount_uplifted"]
  }
}
```

**Key Points:**
- Automatic persona detection from PR analysis
- Test scope decision (test DB, API, UI for this change)
- API field mappings extracted from code

---

### Act 4: Execution - Triple-Check Verification (5 minutes)

**Narration:**
> "Now watch as AutoQA-Reflect executes the test with triple-check verification."

**Demo Steps:**

1. **Trigger Test Execution**
   - Navigate to Task Detail Page
   - Click "Run Tests"
   - Watch the execution log in real-time

2. **Show Gateway Login (Persona Flow):**
   ```
   🔐 Gateway: Logging in as Reseller
   ✓ Clicked: Log In With My Nutanix
   ✓ Filled: Username
   ✓ Filled: Password
   ✓ Selected: CDW partner view
   ✓ Selected: Aaron Ferraro contact
   ✅ Gateway complete - now logged in as Reseller
   ```

3. **Show Navigation:**
   ```
   📍 Navigating to: sales_bookings_page
   ✓ goto: http://localhost:9000/
   ✓ click: a#legend-link-New Logo
   ✓ wait_visible: text=Partner Central
   ```

4. **Show Triple-Check in Action:**

   **Database Check:**
   ```
   🗄️ DB Verification:
   Query: SELECT tcv_amount_uplifted FROM partner_ssot.opportunity WHERE id = $1
   Result: 156723.04
   ✅ Database has correct value
   ```

   **API Check:**
   ```
   🔌 API Verification:
   Captured: GET /api/v1/opportunity
   Field: tcvAmountUplifted = 156723.04
   ✅ API returns correct field
   
   Security Check:
   ❌ SECURITY VIOLATION: 'tcvAmount' found in API response but should be hidden!
   ```

   **UI Check:**
   ```
   🖥️ UI Verification:
   Looking for: TCV column
   Found: $156,723.04
   ✅ UI displays correct value
   ```

5. **Highlight the Bug Found:**
   ```
   ⚠️ TEST FAILED: Security violation detected
   
   For Reseller users:
   - UI correctly shows tcvAmountUplifted ✅
   - But API also exposes tcvAmount (raw value) ❌
   - This is a data security issue!
   
   The backend is leaking sensitive data that the frontend hides.
   ```

---

### Act 5: Results & Reporting (2 minutes)

**Show Execution Report:**
```
╔═══════════════════════════════════════════════════════════════╗
║              EXECUTION REPORT - PPT-20                        ║
╠═══════════════════════════════════════════════════════════════╣
║  Personas Tested: Reseller, Distributor                       ║
║  Total Tests: 4                                                ║
║  Passed: 2 | Failed: 2                                        ║
║                                                               ║
║  FAILURES:                                                    ║
║  ──────────────────────────────────────────────────────────── ║
║  1. verify_tcv_reseller_visibility                            ║
║     SECURITY VIOLATION: tcvAmount exposed in API              ║
║     This field should be hidden for Reseller users            ║
║                                                               ║
║  TRIPLE-CHECK RESULTS:                                        ║
║  ──────────────────────────────────────────────────────────── ║
║  Database:  ✅ All values verified                            ║
║  API:       ❌ Security violation (hidden field exposed)      ║
║  UI:        ✅ Displays correct values                        ║
║                                                               ║
║  RECOMMENDATION:                                              ║
║  Backend should filter out tcvAmount for Reseller users       ║
╚═══════════════════════════════════════════════════════════════╝
```

**Narration:**
> "This bug would be invisible to traditional UI testing. The UI looks perfect—the Reseller sees the correct uplifted value. But the API is leaking the raw data, which could be exploited by inspecting network traffic."

---

## Key Demo Points to Emphasize

### 1. Full-Stack Verification
```
"We're not just clicking buttons and checking text.
We're verifying data at EVERY layer:
- Is it in the database?
- Does the API return it correctly?
- Does the UI display it?

If any layer disagrees, we catch it."
```

### 2. PR-Driven Test Generation
```
"Notice how we didn't write a single test case manually.
The system analyzed the PR diff and generated targeted tests:
- Which fields were added
- Which personas are affected
- Which database columns to verify"
```

### 3. Persona-Aware Testing
```
"The same page behaves differently for Reseller vs Distributor.
We test BOTH perspectives automatically:
- Reseller should see tcvAmountUplifted
- Distributor should see tcvAmount
- We verify each persona's experience is correct"
```

### 4. Security Verification
```
"Most tools can't catch this security bug.
We specifically check that hidden fields don't leak:
- hidden_api_fields: ['tcvAmount']
- If it appears in the API response, we flag it as a violation"
```

### 5. Self-Healing Capability
```
"When selectors break, we don't just fail.
The LLM analyzes the DOM and finds alternatives.
Corrections are learned and persisted for future runs."
```

---

## Q&A Preparation

### "How is this different from Selenium/Cypress?"
> "Traditional tools require you to write tests manually. We generate tests from PR diffs. They only verify UI; we verify DB and API too. They break when selectors change; we self-heal using LLM."

### "What if the LLM makes mistakes?"
> "That's why we have deterministic verification. The LLM helps with navigation and understanding, but the actual checks (DB queries, API validation) are precise code. We also plan a human-in-the-loop approval workflow."

### "How does this scale for large applications?"
> "The semantic graph is incremental. We only re-map pages that changed based on PR diff. Vector search makes finding components O(1) regardless of application size."

### "What about flaky tests?"
> "Most flakiness comes from timing issues and selector brittleness. Our semantic selectors (find by meaning, not ID) and smart waits reduce flakiness. When tests do fail, we distinguish between 'selector issue' (needs healing) and 'actual bug' (needs fixing)."

---

## Closing Statement

> "AutoQA-Reflect isn't just a testing tool—it's your autonomous QA teammate. It understands your application like a senior engineer, knows what changed from your PRs, and verifies correctness at every layer.
>
> Because 'it shows on the UI' doesn't mean the database is correct.
>
> Triple-check verification. That's our promise."
