# Key Features - AutoQA-Reflect

## Core Features

### 1. Semantic Discovery Mapper

**What it does:**
Automatically explores your web application and creates a semantic navigation graph that links UI components to backend systems.

**Technical implementation:**
- Playwright browser automation
- Network interception for API call capture
- LLM-powered semantic naming (not `button_0`, but `create_product_button`)
- ChromaDB vector storage for semantic search

**Output:**
```json
{
  "nodes": [{
    "id": "products_catalog",
    "semantic_name": "products_catalog",
    "components": [{
      "type": "form",
      "role": "create_product_form",
      "selector": "form.product-form",
      "triggers_api": ["POST /products"],
      "impacts_db": "products"
    }]
  }]
}
```

---

### 2. Triple-Check Verification (DB → API → UI)

**What it does:**
Verifies data consistency across all three layers of your application stack.

**Why it matters:**
- UI might show "Success" but DB write failed
- API might return 200 but data is wrong
- Most tools only test one layer

**How it works:**
1. **Database Check**: Query PostgreSQL to verify data was persisted correctly
2. **API Check**: Verify correct endpoints were called with correct payloads
3. **UI Check**: Confirm user can see and interact with the expected elements

**Example verification:**
```
✅ Database: Found record in products table (id=42, name="Test Product")
✅ API: POST /products called, status 201
✅ UI: Product "Test Product" visible in product list
```

---

### 3. PR-Diff Driven Test Generation

**What it does:**
Analyzes GitHub/GitLab PR diffs to automatically generate targeted tests.

**Input:**
```markdown
# Task: Verify new category dropdown
PR Link: https://github.com/org/repo/pull/123
```

**Process:**
1. Fetches PR diff from GitHub API
2. Extracts semantic changes (DB columns, API endpoints, UI components)
3. Finds target node in semantic graph
4. Generates mission.json with test cases

**Output:**
- Targeted test cases based on actual code changes
- Correct selectors from semantic graph
- Appropriate verification points

---

### 4. Context Processor (Intent Extraction)

**What it does:**
Transforms natural language task descriptions into structured test missions.

**Input:**
```
"Test that users can create products with the new category field"
```

**Output:**
```json
{
  "intent": {
    "primary_entity": "Product",
    "changes": ["added category field"],
    "test_focus": "verify category saves correctly"
  },
  "test_cases": [...]
}
```

---

### 5. Hybrid Executor (Deterministic + Agentic)

**What it does:**
Executes tests using a hybrid approach - deterministic when possible, agentic when needed.

**Fast path (deterministic):**
- Uses known selectors from semantic graph
- Direct Playwright commands
- Fast and reliable

**Healer mode (agentic):**
- Activates when selectors fail
- LLM analyzes current DOM
- Finds alternative selectors
- Self-healing capability

---

## Differentiating Features

### 1. Agentic Test Scope Decision

**What makes it unique:**
LLM analyzes PR changes and decides which layers need testing.

**Example:**
- CSS-only change → `test_db: false, test_api: false, test_ui: true`
- New DB column → `test_db: true, test_api: true, test_ui: true`
- API endpoint change → `test_db: false, test_api: true, test_ui: true`

**Benefit:**
- Faster test execution
- Fewer false alarms
- Smarter resource usage

---

### 2. Agentic PR Context Gathering (LangGraph)

**What makes it unique:**
Uses LangGraph workflow to intelligently fetch additional PR context.

**Flow:**
1. Analyze PR diff
2. LLM identifies: "I need more context about this model"
3. Fetches full file contents via GitHub API
4. Merges all context for final analysis

**Benefit:**
- Better understanding of changes
- Fewer hallucinations
- Context-aware test generation

---

### 3. Full-Stack Traceability

**What makes it unique:**
For every UI component, you know:
- **Selector**: How to find it in DOM
- **APIs**: Which endpoints it triggers
- **Database**: Which tables it modifies

**Benefit:**
- Debug issues faster
- Understand impact of changes
- Generate accurate tests

---

### 4. Persona-Aware Mapping

**What makes it unique:**
Maps application state for different user personas (Reseller, Distributor, Internal).

**Implementation:**
- Gateway instructions for login flow
- Separate semantic graphs per persona
- Storage state persistence

**Benefit:**
- Test role-specific features
- Avoid permission-related false failures

---

### 5. Human-in-the-Loop Review (Planned)

**What it will do:**
Display generated test cases for human approval before execution.

**Benefit:**
- Catch LLM hallucinations
- Allow domain expert refinement
- Build trust in the system

---

## Feature Comparison Matrix

| Feature | AutoQA-Reflect | Selenium | Cypress | Playwright | AI Test Tools |
|---------|----------------|----------|---------|------------|---------------|
| Auto-discovery | ✅ | ❌ | ❌ | ❌ | ⚠️ Limited |
| DB verification | ✅ | ❌ | ❌ | ❌ | ❌ |
| API verification | ✅ | ⚠️ Manual | ✅ | ✅ | ⚠️ |
| UI verification | ✅ | ✅ | ✅ | ✅ | ✅ |
| PR-driven | ✅ | ❌ | ❌ | ❌ | ❌ |
| Self-healing | ✅ LLM | ❌ | ❌ | ❌ | ⚠️ Limited |
| Semantic naming | ✅ | ❌ | ❌ | ❌ | ⚠️ |
| Test scope decision | ✅ Agentic | ❌ | ❌ | ❌ | ❌ |
| Vector search | ✅ | ❌ | ❌ | ❌ | ⚠️ |

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Browser Automation | Playwright, browser-use | UI interaction |
| LLM | Nutanix GPT-120B, Ollama | Semantic reasoning |
| Vector Storage | ChromaDB | Semantic search |
| Graph Storage | NetworkX, JSON | Navigation graph |
| Database | PostgreSQL, asyncpg | Test verification |
| Workflow | LangGraph | Agentic orchestration |
| GitHub | PyGithub, httpx | PR context |
| Frontend | React, TypeScript | Dashboard UI |
| Backend | FastAPI | API server |

---

## One-Line Summaries

**For technical audience:**
> "AI-powered QA that verifies data consistency across DB, API, and UI by analyzing PR diffs and generating targeted tests."

**For business audience:**
> "Autonomous QA teammate that catches bugs humans miss by testing the entire application stack, not just what users see."

**For judges:**
> "Triple-check verification: because 'it shows on the UI' doesn't mean the database is correct."
