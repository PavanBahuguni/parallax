# Jira Integration Flow (Planned)

> **Status:** In Development - This document describes the planned Jira integration.

## Overview

AutoQA-Reflect will integrate with Jira to automatically trigger test runs when tickets move to the QA testing lane.

---

## Planned Workflow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Developer   │    │   Jira       │    │  AutoQA      │    │  Test        │
│  moves ticket│───▶│  Webhook     │───▶│  Triggered   │───▶│  Results     │
│  to QA Lane  │    │  fires       │    │  Automatically│   │  in Jira     │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

## What Will Happen

1. **Ticket moves to "QA Testing"** in Jira
2. **Jira webhook fires** to AutoQA-Reflect API
3. **Context Processor** parses ticket + linked PR
4. **Mission generated** with test cases
5. **Executor runs** triple-check verification
6. **Results posted** back to Jira as comment

---

## Jira Webhook Configuration (Planned)

```yaml
# Jira Automation Rule
When: Issue transitioned to "QA Testing"
Then: 
  Send webhook:
    URL: https://autoqa.example.com/api/jira/webhook
    Body:
      issue_key: {{issue.key}}
      summary: {{issue.summary}}
      pr_link: {{issue.customfield_PR_LINK}}
```

---

## Expected Result Format

### Successful Test
```
AutoQA-Reflect Test Results - PPT-20
────────────────────────────────────
Personas: Reseller, Distributor
Tests: 4 passed, 0 failed

Triple-Check:
✅ Database: All values verified
✅ API: All responses correct  
✅ UI: All elements displayed
```

### Failed Test
```
AutoQA-Reflect Test Results - PPT-20
────────────────────────────────────
Personas: Reseller, Distributor
Tests: 2 passed, 2 failed

FAILURE: verify_tcv_reseller_visibility
SECURITY VIOLATION: 'tcvAmount' found in API response but should be hidden

Triple-Check:
✅ Database: All values verified
❌ API: Security violation detected
✅ UI: All elements displayed
```

---

## Benefits

1. **Zero Manual Trigger**: Tests run automatically
2. **Results in Jira**: No context switching
3. **Fast Feedback**: Minutes, not hours
4. **Consistent Testing**: Same tests every time

---

## Future: Test Case Approval (Planned)

Before execution, generated test cases could be displayed for human review:
1. PR analyzed → Test cases generated
2. QA reviews in dashboard
3. Approved tests executed
4. Results reported

This catches LLM hallucinations and allows domain expert refinement.
