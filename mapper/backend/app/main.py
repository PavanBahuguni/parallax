"""FastAPI backend for Agentic QA Dashboard."""
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import traceback

from .schemas import TaskInfo, ExecutionStatus, ExecutionResult, RunTaskRequest
from .agent_orchestrator import AgentOrchestrator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
mapper_dir = Path(__file__).parent.parent.parent
env_file = mapper_dir / ".env"
if env_file.exists():
    load_dotenv(env_file)

app = FastAPI(title="Agentic QA Dashboard API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],  # Vite default ports
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for execution status (for hackathon - could use DB later)
execution_store: Dict[str, ExecutionStatus] = {}

# WebSocket connections for real-time updates (keyed by task_id)
active_websockets: Dict[str, List[WebSocket]] = {}


def get_task_files() -> List[Path]:
    """Get all task.md files from the tasks directory."""
    mapper_dir = Path(__file__).parent.parent.parent
    task_files = []
    
    # Check tasks directory (primary location)
    tasks_dir = mapper_dir / "tasks"
    if tasks_dir.exists():
        # Find all .md files in tasks directory
        for file in tasks_dir.glob("*.md"):
            task_files.append(file)
    
    # Legacy: Check root mapper directory for task.md (backward compatibility)
    task_md = mapper_dir / "task.md"
    if task_md.exists():
        task_files.append(task_md)
    
    # Legacy: Check for TASK-*_task.md files in root (backward compatibility)
    for file in mapper_dir.glob("TASK-*_task.md"):
        task_files.append(file)
    
    # Legacy: Check temp directory for task files (backward compatibility)
    temp_dir = mapper_dir / "temp"
    if temp_dir.exists():
        for file in temp_dir.glob("*task*.md"):
            task_files.append(file)
    
    return task_files


def parse_task_file(task_path: Path) -> Dict[str, Any]:
    """Parse a task.md file and extract information."""
    mapper_dir = Path(__file__).parent.parent.parent
    content = task_path.read_text()
    
    # Extract title (first line after #)
    title = "Unknown Task"
    description = ""
    pr_link = None
    
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('# '):
            title = line[2:].strip()
        elif line.startswith('## Description'):
            # Get description until next ##
            desc_lines = []
            for j in range(i + 1, len(lines)):
                if lines[j].startswith('##'):
                    break
                desc_lines.append(lines[j])
            description = '\n'.join(desc_lines).strip()
        elif 'PR Link' in line or 'pr_link' in line.lower() or '## PR Link' in line:
            # Try to extract PR link
            for j in range(i, min(i + 3, len(lines))):
                if 'http' in lines[j]:
                    pr_link = lines[j].strip()
                    break
    
    # Extract task ID from file header first (most reliable)
    # Look for "# TASK-X:" pattern in the first few lines
    task_id = None
    for i, line in enumerate(lines[:5]):  # Check first 5 lines
        if line.startswith('# '):
            # Extract TASK-X from header like "# TASK-2: Add Category Field"
            match = re.search(r'TASK-(\d+)', line, re.IGNORECASE)
            if match:
                task_id = f"TASK-{match.group(1)}"
                break
    
    # Fallback: Generate task ID from filename
    if not task_id:
        task_id = task_path.stem.upper()
        if task_id == "TASK":
            task_id = "TASK-1"  # Default for root task.md
        elif task_id.startswith("TASK-"):
            # Already formatted (e.g., TASK-1_task -> TASK-1)
            # Extract just the TASK-X part
            match = re.search(r'TASK-(\d+)', task_id)
            if match:
                task_id = f"TASK-{match.group(1)}"
        else:
            # Convert to TASK-X format
            task_id = task_id.replace('_', '-').replace(' ', '-')
            if not task_id.startswith("TASK-"):
                task_id = f"TASK-{task_id}"
    
    # Get file stats
    stat = task_path.stat()
    
    return {
        "id": task_id,
        "title": title,
        "description": description or content[:200] + "..." if len(content) > 200 else content,
        "pr_link": pr_link,
        "file_path": str(task_path.relative_to(mapper_dir)),
        "created_at": datetime.fromtimestamp(stat.st_birthtime) if hasattr(stat, 'st_birthtime') else datetime.fromtimestamp(stat.st_mtime),
        "updated_at": datetime.fromtimestamp(stat.st_mtime),
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Agentic QA Dashboard API", "version": "1.0.0"}


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy"}


@app.get("/tasks", response_model=List[TaskInfo])
async def list_tasks():
    """List all available tasks."""
    try:
        task_files = get_task_files()
        tasks = [parse_task_file(f) for f in task_files]
        return tasks
    except Exception as e:
        logger.error(f"Error listing tasks: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get details of a specific task."""
    try:
        task_files = get_task_files()
        # Find task file matching task_id
        for task_file in task_files:
            parsed = parse_task_file(task_file)
            if parsed["id"].upper() == task_id.upper():
                return parsed
        
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def run_semantic_mapper(task_id: str, execution_id: str):
    """Run semantic mapper in background."""
    try:
        execution_store[execution_id].status = "running"
        
        mapper_dir = Path(__file__).parent.parent.parent
        script_path = mapper_dir / "semantic_mapper.py"
        graph_file = mapper_dir / "semantic_graph.json"
        
        # Run semantic mapper
        process = await asyncio.create_subprocess_exec(
            "uv", "run", "python", str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # Combine stderr with stdout
            cwd=str(mapper_dir)
        )
        
        stdout, _ = await process.communicate()
        output = stdout.decode() if stdout else ""
        
        result = {
            "output": output,
            "success": process.returncode == 0,
            "graph_file": str(graph_file.relative_to(mapper_dir)) if graph_file.exists() else None
        }
        
        # If graph was created, include summary
        if graph_file.exists():
            try:
                graph_data = json.loads(graph_file.read_text())
                result["graph"] = {
                    "nodes_count": len(graph_data.get("nodes", [])),
                    "edges_count": len(graph_data.get("edges", [])),
                    "nodes": graph_data.get("nodes", []),
                    "edges": graph_data.get("edges", [])
                }
            except Exception as e:
                logger.warning(f"Could not parse semantic graph: {e}")
        
        if process.returncode == 0:
            execution_store[execution_id].status = "completed"
            execution_store[execution_id].result = result
        else:
            execution_store[execution_id].status = "failed"
            execution_store[execution_id].error = output or "Unknown error"
            execution_store[execution_id].result = result
        
        execution_store[execution_id].completed_at = datetime.now()
        
    except Exception as e:
        execution_store[execution_id].status = "failed"
        execution_store[execution_id].error = str(e)
        execution_store[execution_id].completed_at = datetime.now()
        logger.error(f"Error running semantic mapper: {e}")
        logger.error(traceback.format_exc())


async def run_context_processor(task_id: str, execution_id: str):
    """Run context processor to generate mission.json."""
    try:
        execution_store[execution_id].status = "running"
        
        mapper_dir = Path(__file__).parent.parent.parent
        script_path = mapper_dir / "context_processor.py"
        
        # Find the task file matching task_id
        task_files = get_task_files()
        task_file_path = None
        for task_file in task_files:
            parsed = parse_task_file(task_file)
            if parsed["id"].upper() == task_id.upper():
                task_file_path = task_file
                break
        
        if not task_file_path:
            # Fallback: try to find by filename pattern
            for task_file in task_files:
                if task_id.upper() in task_file.stem.upper():
                    task_file_path = task_file
                    break
        
        if not task_file_path:
            # Last resort: try tasks directory, then root
            tasks_dir = mapper_dir / "tasks"
            if tasks_dir.exists():
                # Try to find by task_id in tasks directory
                for file in tasks_dir.glob("*.md"):
                    parsed = parse_task_file(file)
                    if parsed["id"].upper() == task_id.upper():
                        task_file_path = file
                        break
                    # Also check filename
                    if task_id.upper() in file.stem.upper():
                        task_file_path = file
                        break
            
            # Final fallback: use task.md in tasks directory or root
            if not task_file_path:
                task_file_path = tasks_dir / "task.md" if (tasks_dir / "task.md").exists() else mapper_dir / "task.md"
                if not task_file_path.exists():
                    available_tasks = [parse_task_file(f)['id'] for f in task_files] if task_files else []
                    raise FileNotFoundError(f"Task file not found for {task_id}. Available tasks: {available_tasks}")
        
        logger.info(f"Using task file: {task_file_path} for task_id: {task_id}")
        
        # Run context processor with the specific task file
        process = await asyncio.create_subprocess_exec(
            "uv", "run", "python", str(script_path), str(task_file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # Combine stderr with stdout
            cwd=str(mapper_dir)
        )
        
        stdout, _ = await process.communicate()
        output = stdout.decode() if stdout else ""
        
        # Check if mission.json was created
        # Context processor generates based on ticket_id extracted from task file
        # It should generate: temp/{task_name}_mission.json where task_name comes from ticket_id or filename
        mission_file = mapper_dir / "temp" / f"{task_id}_mission.json"
        
        # If not found, check for mission.json in root (old behavior)
        if not mission_file.exists():
            root_mission = mapper_dir / "mission.json"
            if root_mission.exists():
                # Read it to check ticket_id
                try:
                    mission_data = json.loads(root_mission.read_text())
                    mission_ticket_id = mission_data.get("ticket_id", "").upper()
                    # If ticket_id matches task_id, rename it
                    if mission_ticket_id == task_id.upper():
                        shutil.move(str(root_mission), str(mission_file))
                        logger.info(f"Moved mission.json to {mission_file}")
                    else:
                        # Create a copy with correct name
                        mission_file.write_text(root_mission.read_text())
                        logger.info(f"Created {mission_file} from mission.json")
                except Exception as e:
                    logger.warning(f"Could not process root mission.json: {e}")
        
        result = {
            "output": output,
            "success": process.returncode == 0,
            "mission_file": str(mission_file.relative_to(mapper_dir)) if mission_file.exists() else None
        }
        
        if mission_file.exists():
            try:
                mission_data = json.loads(mission_file.read_text())
                result["mission"] = mission_data
            except Exception as e:
                logger.warning(f"Could not parse mission JSON: {e}")
        
        if process.returncode == 0:
            execution_store[execution_id].status = "completed"
            execution_store[execution_id].result = result
        else:
            execution_store[execution_id].status = "failed"
            execution_store[execution_id].error = output or "Unknown error"
            execution_store[execution_id].result = result
        
        execution_store[execution_id].completed_at = datetime.now()
        
    except Exception as e:
        execution_store[execution_id].status = "failed"
        execution_store[execution_id].error = str(e)
        execution_store[execution_id].completed_at = datetime.now()
        logger.error(f"Error running context processor: {e}")
        logger.error(traceback.format_exc())


async def run_executor(task_id: str, execution_id: str, mission_file: Optional[str] = None):
    """Run executor to execute test."""
    try:
        execution_store[execution_id].status = "running"
        
        mapper_dir = Path(__file__).parent.parent.parent
        script_path = mapper_dir / "executor.py"
        
        # Determine mission file
        if not mission_file:
            mission_file_path = mapper_dir / "temp" / f"{task_id}_mission.json"
            if not mission_file_path.exists():
                mission_file_path = mapper_dir / "mission.json"
        else:
            mission_file_path = mapper_dir / mission_file
        
        if not mission_file_path.exists():
            raise FileNotFoundError(f"Mission file not found: {mission_file_path}")
        
        # Run executor
        # Prepare environment without VIRTUAL_ENV to avoid uv warnings
        import os
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        
        process = await asyncio.create_subprocess_exec(
            "uv", "run", "python", str(script_path), str(mission_file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # Combine stderr with stdout
            cwd=str(mapper_dir),
            env=env
        )
        
        stdout, _ = await process.communicate()
        output = stdout.decode() if stdout else ""
        
        # Check for report file
        report_file = mapper_dir / "temp" / f"{mission_file_path.stem}_report.json"
        
        result = {
            "output": output,
            "success": process.returncode == 0,
            "report_file": str(report_file.relative_to(mapper_dir)) if report_file.exists() else None
        }
        
        if report_file.exists():
            try:
                report_data = json.loads(report_file.read_text())
                result["report"] = report_data
            except Exception as e:
                logger.warning(f"Could not parse report JSON: {e}")
        
        if process.returncode == 0:
            execution_store[execution_id].status = "completed"
            execution_store[execution_id].result = result
        else:
            execution_store[execution_id].status = "failed"
            execution_store[execution_id].error = output or "Unknown error"
            execution_store[execution_id].result = result
        
        execution_store[execution_id].completed_at = datetime.now()
        
    except Exception as e:
        execution_store[execution_id].status = "failed"
        execution_store[execution_id].error = str(e)
        execution_store[execution_id].completed_at = datetime.now()
        logger.error(f"Error running executor: {e}")
        logger.error(traceback.format_exc())


@app.post("/tasks/{task_id}/run", response_model=ExecutionStatus)
async def run_task_operation(
    task_id: str,
    request: RunTaskRequest,
    background_tasks: BackgroundTasks
):
    """Run a task operation (map, generate-mission, or execute)."""
    try:
        execution_id = str(uuid.uuid4())
        
        # Create execution status
        execution_status = ExecutionStatus(
            execution_id=execution_id,
            task_id=task_id,
            status="pending",
            started_at=datetime.now(),
            execution_type=request.operation,
            result=None,
            error=None
        )
        
        execution_store[execution_id] = execution_status
        
        # Run appropriate operation in background
        if request.operation == "map":
            background_tasks.add_task(run_semantic_mapper, task_id, execution_id)
        elif request.operation == "generate-mission":
            background_tasks.add_task(run_context_processor, task_id, execution_id)
        elif request.operation == "execute":
            mission_file = request.options.get("mission_file") if request.options else None
            background_tasks.add_task(run_executor, task_id, execution_id, mission_file)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown operation: {request.operation}")
        
        return execution_status
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting task operation: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/executions", response_model=List[ExecutionStatus])
async def list_executions(task_id: Optional[str] = None):
    """List all executions, optionally filtered by task_id."""
    executions = list(execution_store.values())
    
    if task_id:
        executions = [e for e in executions if e.task_id.upper() == task_id.upper()]
    
    # Sort by started_at descending
    executions.sort(key=lambda x: x.started_at, reverse=True)
    
    return executions


@app.get("/executions/{execution_id}", response_model=ExecutionResult)
async def get_execution(execution_id: str):
    """Get detailed execution result."""
    if execution_id not in execution_store:
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
    
    execution = execution_store[execution_id]
    
    return ExecutionResult(
        execution_id=execution.execution_id,
        task_id=execution.task_id,
        execution_type=execution.execution_type,
        status=execution.status,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        result=execution.result or {},
        error=execution.error
    )


@app.get("/semantic-graph")
async def get_semantic_graph():
    """Get the semantic graph JSON."""
    try:
        mapper_dir = Path(__file__).parent.parent.parent
        graph_file = mapper_dir / "semantic_graph.json"
        
        if not graph_file.exists():
            raise HTTPException(status_code=404, detail="Semantic graph not found")
        
        graph_data = json.loads(graph_file.read_text())
        return graph_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading semantic graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/tasks/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time workflow updates."""
    await websocket.accept()
    
    # Add to active connections
    if task_id not in active_websockets:
        active_websockets[task_id] = []
    active_websockets[task_id].append(websocket)
    
    try:
        # Keep connection alive and send updates
        while True:
            # Wait for client messages (ping/pong)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        # Remove from active connections
        if task_id in active_websockets:
            active_websockets[task_id].remove(websocket)
            if not active_websockets[task_id]:
                del active_websockets[task_id]


async def broadcast_update(task_id: str, update: Dict[str, Any]):
    """Broadcast update to all WebSocket connections for a task."""
    if task_id in active_websockets:
        disconnected = []
        for ws in active_websockets[task_id]:
            try:
                await ws.send_json(update)
            except Exception as e:
                logger.warning(f"Error sending WebSocket update: {e}")
                disconnected.append(ws)
        
        # Remove disconnected connections
        for ws in disconnected:
            active_websockets[task_id].remove(ws)
        if not active_websockets[task_id]:
            del active_websockets[task_id]


@app.post("/tasks/{task_id}/run-automated", response_model=ExecutionStatus)
async def run_automated_workflow(
    task_id: str,
    background_tasks: BackgroundTasks
):
    """Run automated workflow: intelligently run Map → Generate Mission → Execute."""
    try:
        execution_id = str(uuid.uuid4())
        
        # Find task file
        task_files = get_task_files()
        task_file_path = None
        for task_file in task_files:
            parsed = parse_task_file(task_file)
            if parsed["id"].upper() == task_id.upper():
                task_file_path = task_file
                break
        
        if not task_file_path:
            # Fallback
            tasks_dir = Path(__file__).parent.parent.parent / "tasks"
            task_file_path = tasks_dir / f"{task_id}_task.md"
            if not task_file_path.exists():
                task_file_path = tasks_dir / "task.md"
        
        if not task_file_path.exists():
            raise HTTPException(status_code=404, detail=f"Task file not found for {task_id}")
        
        # Get PR link from task
        parsed_task = parse_task_file(task_file_path)
        pr_link = parsed_task.get("pr_link")
        
        # Create execution status
        execution_status = ExecutionStatus(
            execution_id=execution_id,
            task_id=task_id,
            status="pending",
            started_at=datetime.now(),
            execution_type="automated-workflow",
            result=None,
            error=None
        )
        
        execution_store[execution_id] = execution_status
        
        # Create orchestrator with update callback
        async def update_callback(update: Dict[str, Any]):
            """Send updates via WebSocket and update execution store."""
            try:
                # Broadcast to WebSocket clients
                await broadcast_update(task_id, update)
                
                # Also update execution store
                if execution_id in execution_store:
                    if not execution_store[execution_id].result:
                        execution_store[execution_id].result = {"updates": []}
                    if "updates" not in execution_store[execution_id].result:
                        execution_store[execution_id].result["updates"] = []
                    execution_store[execution_id].result["updates"].append(update)
                    
                    # Log for debugging
                    logger.info(f"Workflow update [{update.get('step')}]: {update.get('status')} - {update.get('message')}")
            except Exception as e:
                logger.error(f"Error in update callback: {e}")
                # Don't fail the workflow if WebSocket fails
        
        # Run workflow in background
        async def run_workflow():
            try:
                execution_store[execution_id].status = "running"
                
                # Small delay to ensure WebSocket connection is established
                await asyncio.sleep(0.5)
                
                orchestrator = AgentOrchestrator(update_callback=update_callback)
                results = await orchestrator.run_full_workflow(
                    task_id, task_file_path, pr_link
                )
                
                execution_store[execution_id].status = "completed" if results.get("overall_success") else "failed"
                execution_store[execution_id].result = results
                execution_store[execution_id].completed_at = datetime.now()
                
            except Exception as e:
                execution_store[execution_id].status = "failed"
                execution_store[execution_id].error = str(e)
                execution_store[execution_id].completed_at = datetime.now()
                logger.error(f"Automated workflow error: {e}")
                logger.error(traceback.format_exc())
        
        background_tasks.add_task(run_workflow)
        
        return execution_status
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting automated workflow: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
