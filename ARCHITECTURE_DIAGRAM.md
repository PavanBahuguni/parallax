# Agentic QA System - Visual Architecture Diagram

## Mermaid Flow Diagram

```mermaid
graph TB
    subgraph "Phase 0: Semantic Discovery"
        A[Web App Running] -->|Playwright| B[semantic_mapper.py]
        B -->|LLM: Nutanix GPT-120B| C[Semantic Component Naming]
        B -->|Network Interception| D[API Calls Capture]
        B -->|ChromaDB| E[Vector Storage]
        C --> F[semantic_graph.json]
        D --> F
    end

    subgraph "Phase 1: Context Processor"
        G[task.md] -->|Parse| H[context_processor.py]
        I[PR Link] -->|GitHub API| J[PR Diff Analysis]
        J -->|Extract| K[DB Columns, API Endpoints]
        H -->|LLM: Nutanix GPT-120B| L[Intent Extraction]
        L --> M[Find Target Node]
        K --> N[Generate Test Data]
        M --> N
        N --> O[mission.json]
    end

    subgraph "Phase 2: Triple-Check Executor"
        O -->|Read| P[executor.py]
        P -->|Fast Path| Q[Deterministic Execution]
        Q -->|Success?| R{Result}
        R -->|No| S[Healer Mode]
        S -->|LLM: Nutanix GPT-120B| T[Selector Recovery]
        T --> Q
        R -->|Yes| U[Triple-Check]
        U --> V[1. Database Query]
        U --> W[2. API Verification]
        U --> X[3. UI Verification]
        V --> Y[report.json]
        W --> Y
        X --> Y
    end

    subgraph "Data Storage"
        E
        F
        Z[PostgreSQL<br/>items table]
        AA[ChromaDB<br/>agent_memory/]
    end

    style B fill:#e1f5ff
    style H fill:#e1f5ff
    style P fill:#e1f5ff
    style C fill:#fff4e1
    style L fill:#fff4e1
    style T fill:#fff4e1
```

## Component Interaction Diagram

```mermaid
graph LR
    subgraph "Inputs"
        A[task.md<br/>Human Intent]
        B[PR Link<br/>GitHub]
        C[Web App<br/>Running]
    end

    subgraph "Processing"
        D[semantic_mapper.py<br/>Playwright + LLM]
        E[context_processor.py<br/>LLM + GitHub API]
        F[executor.py<br/>Playwright + PostgreSQL]
    end

    subgraph "LLM Usage"
        G[Nutanix GPT-120B<br/>Semantic Naming]
        H[Nutanix GPT-120B<br/>Intent Extraction]
        I[Nutanix GPT-120B<br/>Selector Recovery]
    end

    subgraph "Outputs"
        J[semantic_graph.json]
        K[mission.json]
        L[report.json]
    end

    C --> D
    D --> G
    G --> J

    A --> E
    B --> E
    E --> H
    H --> K

    K --> F
    F --> I
    F --> L

    style G fill:#ffd700
    style H fill:#ffd700
    style I fill:#ffd700
```

## Library Dependencies Graph

```mermaid
graph TD
    A[Agentic QA System] --> B[Browser Automation]
    A --> C[LLM Integration]
    A --> D[Data Storage]
    A --> E[Graph Processing]

    B --> B1[playwright]
    B --> B2[browser-use]

    C --> C1[httpx]
    C --> C2[FixedNutanixChatModel]
    C2 --> C3[Nutanix API<br/>openai/gpt-oss-120b]

    D --> D1[ChromaDB<br/>Vector Storage]
    D --> D2[PostgreSQL<br/>asyncpg]
    D --> D3[JSON Files]

    E --> E1[networkx]
    E --> E2[graph_queries.py]

    A --> F[Utilities]
    F --> F1[rich<br/>Terminal Output]
    F --> F2[pygithub<br/>GitHub API]
    F --> F3[pydantic<br/>Data Validation]

    style C3 fill:#ffd700
```

## Triple-Check Flow

```mermaid
sequenceDiagram
    participant E as executor.py
    participant P as Playwright
    participant DB as PostgreSQL
    participant API as FastAPI Backend
    participant UI as React Frontend

    E->>P: Navigate to target_url
    E->>P: Fill form fields
    E->>P: Click submit
    P->>API: POST /items
    API->>DB: INSERT INTO items
    API->>UI: Return created item
    UI->>P: Display new item
    
    Note over E: Triple-Check Verification
    
    E->>DB: Query: SELECT * FROM items<br/>WHERE tag = 'test-tag'
    DB-->>E: ✅ Record found
    
    E->>E: Check captured API calls
    E-->>E: ✅ POST /items called
    
    E->>P: Check UI for item + tag
    P-->>E: ✅ Item and tag visible
    
    E->>E: Generate report.json
```

## LLM Usage Points

```mermaid
graph TB
    subgraph "1. Semantic Mapper"
        A1[DOM Structure] -->|Input| LLM1[Nutanix GPT-120B]
        LLM1 -->|Output| A2[Semantic Names<br/>create_item_form]
    end

    subgraph "2. Context Processor"
        B1[Task Description] -->|Input| LLM2[Nutanix GPT-120B]
        LLM2 -->|Output| B2[Structured Intent<br/>entity, changes, focus]
    end

    subgraph "3. Executor Healer"
        C1[DOM Snapshot<br/>Failed Selector] -->|Input| LLM3[Nutanix GPT-120B]
        LLM3 -->|Output| C2[New Selector<br/>Reasoning]
    end

    style LLM1 fill:#ffd700
    style LLM2 fill:#ffd700
    style LLM3 fill:#ffd700
```

## Data Flow

```mermaid
flowchart LR
    A[task.md] -->|Parse| B[Context Processor]
    C[PR Link] -->|GitHub API| B
    D[semantic_graph.json] -->|Query| B
    B -->|Generate| E[mission.json]
    
    E -->|Read| F[Executor]
    G[PostgreSQL] -->|Query| F
    H[Playwright] -->|Control| F
    F -->|Generate| I[report.json]
    
    J[Web App] -->|Explore| K[Semantic Mapper]
    K -->|Store| L[ChromaDB]
    K -->|Generate| D
    
    style B fill:#e1f5ff
    style F fill:#e1f5ff
    style K fill:#e1f5ff
```
