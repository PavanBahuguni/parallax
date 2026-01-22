# Agentic QA Dashboard Backend

FastAPI backend for the Agentic QA Dashboard.

## Setup

```bash
cd backend
uv sync
```

## Run

```bash
uv run uvicorn app.main:app --reload --port 8001
```

The API will be available at `http://localhost:8001`

## API Endpoints

- `GET /` - Root endpoint
- `GET /health` - Health check
- `GET /tasks` - List all tasks
- `GET /tasks/{task_id}` - Get task details
- `POST /tasks/{task_id}/run` - Run task operation (map, generate-mission, execute)
- `GET /executions` - List all executions
- `GET /executions/{execution_id}` - Get execution result
- `GET /semantic-graph` - Get semantic graph JSON
