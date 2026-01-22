# Agentic QA Dashboard

A web-based dashboard for managing and executing Agentic QA tasks, tests, and viewing results.

## Architecture

- **Backend**: FastAPI (Python) running on port 8001
- **Frontend**: React + Vite + TypeScript running on port 5174

## Quick Start

### Backend Setup

```bash
cd mapper/backend
uv sync
uv run uvicorn app.main:app --reload --port 8001
```

### Frontend Setup

```bash
cd mapper/frontend
npm install
npm run dev
```

The dashboard will be available at `http://localhost:5174`

## Features

### Dashboard Page
- View all tasks from `task.md` files
- Task cards showing title, description, and PR link
- Navigate to task details

### Task Detail Page
- View full task description
- Run operations:
  - **🗺️ Run Semantic Mapper**: Discover UI routes and build semantic graph
  - **📝 Generate Mission**: Process task and PR to generate mission.json
  - **▶️ Execute Test**: Run the test executor with triple-check verification
- View execution history for the task
- Real-time status updates

### Executions Page
- View all executions across all tasks
- Filter by task
- See execution status (pending, running, completed, failed)
- Expand to view detailed results and errors

## API Endpoints

### Tasks
- `GET /api/tasks` - List all tasks
- `GET /api/tasks/{task_id}` - Get task details
- `POST /api/tasks/{task_id}/run` - Run task operation

### Executions
- `GET /api/executions` - List all executions
- `GET /api/executions/{execution_id}` - Get execution details

### Other
- `GET /api/semantic-graph` - Get semantic graph JSON

## Usage Flow

1. **Create a task**: Add a `task.md` file in the mapper directory describing your test scenario
2. **Run Semantic Mapper**: Click "Run Semantic Mapper" to discover UI routes and build the semantic graph
3. **Generate Mission**: Click "Generate Mission" to process the task and PR diff, generating a `mission.json` file
4. **Execute Test**: Click "Execute Test" to run the test executor, which will:
   - Navigate to the target page
   - Fill forms and interact with UI
   - Verify database changes
   - Verify API calls
   - Verify UI updates
5. **View Results**: Check the execution history to see detailed results and any errors

## Development

### Backend Development
- Backend code: `mapper/backend/app/`
- Main API: `mapper/backend/app/main.py`
- Schemas: `mapper/backend/app/schemas.py`

### Frontend Development
- Frontend code: `mapper/frontend/src/`
- Pages: `mapper/frontend/src/pages/`
- Components: `mapper/frontend/src/components/`
- API client: `mapper/frontend/src/api/client.ts`

## Notes

- Executions are stored in-memory (for hackathon demo). For production, consider using a database.
- The backend runs Python scripts using `uv run python` - make sure `uv` is installed and configured.
- The frontend polls for execution updates every 2 seconds when viewing the executions page.
