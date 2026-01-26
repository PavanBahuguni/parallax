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
from uuid import UUID
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import traceback

from .schemas import (
    TaskInfo, ExecutionStatus, ExecutionResult, RunTaskRequest,
    ProjectCreate, ProjectUpdate, ProjectInfo,
    TaskCreate, TaskUpdate, RegenerateSemanticMapsRequest
)
from .agent_orchestrator import AgentOrchestrator
from .database import get_db, init_db
from .models import Project, Task, ProjectConfig

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


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"Database initialization failed (may not be connected): {e}")

# In-memory storage for execution status (for hackathon - could use DB later)
execution_store: Dict[str, ExecutionStatus] = {}

# WebSocket connections for real-time updates (keyed by task_id)
active_websockets: Dict[str, List[WebSocket]] = {}


# ============================================================================
# PROJECT ENDPOINTS
# ============================================================================

@app.post("/api/projects", response_model=ProjectInfo)
async def create_project(project_data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    """Create a new project."""
    try:
        # Convert PersonaInfo objects to dict format for JSONB storage
        personas_data = []
        if project_data.personas:
            for persona in project_data.personas:
                personas_data.append({
                    "name": persona.name,
                    "gateway_instructions": persona.gateway_instructions
                })
        
        project = Project(
            name=project_data.name,
            description=project_data.description,
            ui_url=project_data.ui_url,
            api_base_url=project_data.api_base_url,
            openapi_url=project_data.openapi_url,
            database_url=project_data.database_url,
            backend_path=project_data.backend_path,
            personas=personas_data,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        return ProjectInfo(**project.to_dict())
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects", response_model=List[ProjectInfo])
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List all projects."""
    try:
        result = await db.execute(select(Project))
        projects = result.scalars().all()
        return [ProjectInfo(**project.to_dict()) for project in projects]
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error listing projects: {e}")
        # Check if it's a database doesn't exist error
        if "does not exist" in error_msg.lower() or "database" in error_msg.lower():
            logger.warning("Database not found. Please run: python mapper/backend/scripts/setup_database.py")
        # Fallback to empty list if DB not available
        return []


@app.get("/api/projects/{project_id}", response_model=ProjectInfo)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific project."""
    try:
        project_uuid = UUID(project_id)
        result = await db.execute(select(Project).where(Project.id == project_uuid))
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        return ProjectInfo(**project.to_dict())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid project ID: {project_id}")
    except Exception as e:
        logger.error(f"Error getting project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/projects/{project_id}", response_model=ProjectInfo)
async def update_project(
    project_id: str,
    project_data: ProjectUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a project."""
    try:
        project_uuid = UUID(project_id)
        result = await db.execute(select(Project).where(Project.id == project_uuid))
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        
        # Update fields
        update_data = project_data.model_dump(exclude_unset=True)
        
        # Handle personas conversion if present
        if "personas" in update_data:
            personas_data = []
            for persona in update_data["personas"]:
                if isinstance(persona, dict):
                    personas_data.append({
                        "name": persona.get("name", ""),
                        "gateway_instructions": persona.get("gateway_instructions", "")
                    })
            update_data["personas"] = personas_data
        
        for key, value in update_data.items():
            setattr(project, key, value)
        
        project.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(project)
        return ProjectInfo(**project.to_dict())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid project ID: {project_id}")
    except Exception as e:
        logger.error(f"Error updating project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a project."""
    try:
        project_uuid = UUID(project_id)
        result = await db.execute(select(Project).where(Project.id == project_uuid))
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        
        await db.delete(project)
        await db.commit()
        return {"message": f"Project {project_id} deleted successfully"}
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid project ID: {project_id}")
    except Exception as e:
        logger.error(f"Error deleting project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_id}/regenerate-semantic-maps")
async def regenerate_semantic_maps(
    project_id: str,
    request: RegenerateSemanticMapsRequest = RegenerateSemanticMapsRequest(),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db)
):
    """Regenerate semantic maps for all personas in a project.
    
    This will run semantic_mapper_with_gateway.py for each persona defined in the project,
    generating separate graph files for each persona.
    
    Args:
        project_id: Project ID
        request: Request body with headless flag (default: True)
    """
    try:
        # Load project config
        from .project_config import load_project_config, get_config_for_execution, get_persona_gateway_instructions
        
        project_config = await load_project_config(project_id, db)
        if not project_config:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        
        execution_config = get_config_for_execution(project_config)
        personas = execution_config.get("PERSONAS", [])
        
        if not personas:
            raise HTTPException(status_code=400, detail="Project has no personas defined")
        
        # Create execution ID for tracking
        execution_id = str(uuid.uuid4())
        
        # Create execution status
        execution_status = ExecutionStatus(
            execution_id=execution_id,
            task_id="regenerate-maps",
            status="pending",
            started_at=datetime.now(),
            execution_type="regenerate-semantic-maps",
            result=None,
            error=None
        )
        
        execution_store[execution_id] = execution_status
        
        # Run regeneration in background
        background_tasks.add_task(
            run_semantic_map_regeneration,
            project_id,
            execution_id,
            execution_config,
            personas,
            request.headless
        )
        
        return {
            "execution_id": execution_id,
            "message": f"Started regeneration for {len(personas)} persona(s)",
            "personas": [p.get("name") if isinstance(p, dict) else p for p in personas]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting semantic map regeneration: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


async def run_semantic_map_regeneration(
    project_id: str,
    execution_id: str,
    project_config: Dict[str, Any],
    personas: List[Any],
    headless: bool = True
):
    """Run semantic map regeneration for all personas in background."""
    try:
        execution_store[execution_id].status = "running"
        
        mapper_dir = Path(__file__).parent.parent.parent
        script_path = mapper_dir / "semantic_mapper_with_gateway.py"
        temp_dir = mapper_dir / "temp"
        temp_dir.mkdir(exist_ok=True)
        
        results = []
        base_url = project_config.get("BASE_URL", "http://localhost:5173")
        
        for persona_obj in personas:
            # Extract persona name
            if isinstance(persona_obj, dict):
                persona_name = persona_obj.get("name", "")
                gateway_instructions = persona_obj.get("gateway_instructions", "")
            else:
                persona_name = str(persona_obj)
                gateway_instructions = ""
            
            if not persona_name:
                logger.warning(f"Skipping persona with no name: {persona_obj}")
                continue
            
            logger.info(f"Regenerating semantic map for persona: {persona_name}")
            
            # Create temporary gateway instructions file if needed
            gateway_file = None
            if gateway_instructions:
                gateway_file = temp_dir / f"gateway_{persona_name}.txt"
                gateway_file.write_text(gateway_instructions)
                logger.info(f"Created gateway instructions file: {gateway_file}")
            
            # Prepare output file
            output_file = mapper_dir / f"semantic_graph_{persona_name}.json"
            gateway_plan_file = temp_dir / f"gateway_plan_{persona_name}.json"
            
            # Prepare environment
            env = os.environ.copy()
            env["PROJECT_BASE_URL"] = base_url
            env["PROJECT_API_BASE"] = project_config.get("API_BASE", "")
            env["PROJECT_BACKEND_PATH"] = project_config.get("BACKEND_PATH", "")
            
            # Build command - use gateway plan instead of storage state
            cmd = [
                "uv", "run", "python", str(script_path),
                "--persona", persona_name,
                "--gateway-plan", str(gateway_plan_file),
                "--output", str(output_file),
                "--base-url", base_url,
                "--headless", "true" if headless else "false",
                "--max-depth", "3"
            ]
            
            # Add gateway instructions if provided (will compile plan on first run, reuse on subsequent runs)
            # Always pass instructions to ensure hash check works - if instructions changed, plan will be recompiled
            if gateway_file and gateway_file.exists():
                cmd.extend(["--gateway-instructions", str(gateway_file)])
                # Force recompile if plan exists but instructions file is newer (safety check)
                if gateway_plan_file.exists():
                    import time
                    instructions_mtime = gateway_file.stat().st_mtime
                    plan_mtime = gateway_plan_file.stat().st_mtime
                    if instructions_mtime > plan_mtime:
                        logger.info(f"Gateway instructions file is newer than plan - will force recompile")
                        cmd.append("--force-recompile-gateway")
            else:
                cmd.append("--skip-gateway")
            
            # Run semantic mapper
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(mapper_dir),
                env=env
            )
            
            stdout, _ = await process.communicate()
            output = stdout.decode() if stdout else ""
            
            success = process.returncode == 0
            
            result = {
                "persona": persona_name,
                "success": success,
                "output": output,
                "graph_file": str(output_file.relative_to(mapper_dir)) if output_file.exists() else None
            }
            
            # If graph was created, include summary and auto-index to ChromaDB
            if output_file.exists():
                try:
                    graph_data = json.loads(output_file.read_text())
                    result["graph"] = {
                        "nodes_count": len(graph_data.get("nodes", [])),
                        "edges_count": len(graph_data.get("edges", [])),
                    }
                    
                    # Automatically index the graph to ChromaDB for semantic search
                    if success:
                        try:
                            logger.info(f"📝 Auto-indexing semantic graph for persona: {persona_name}")
                            # Import GraphQueries here to avoid circular imports
                            import sys
                            mapper_dir_str = str(mapper_dir)
                            if mapper_dir_str not in sys.path:
                                sys.path.insert(0, mapper_dir_str)
                            
                            from graph_queries import GraphQueries
                            
                            # Index the persona-specific graph
                            queries = GraphQueries(persona=persona_name)
                            queries.index_graph_to_chromadb(force_reindex=True)
                            logger.info(f"✅ Successfully auto-indexed graph for persona: {persona_name}")
                            result["indexed"] = True
                        except Exception as index_error:
                            # Don't fail the whole regeneration if indexing fails
                            logger.warning(f"⚠️  Failed to auto-index graph for persona {persona_name}: {index_error}")
                            logger.debug(traceback.format_exc())
                            result["indexed"] = False
                            result["index_error"] = str(index_error)
                except Exception as e:
                    logger.warning(f"Could not parse semantic graph for {persona_name}: {e}")
            
            results.append(result)
            
            if success:
                logger.info(f"✅ Successfully generated semantic map for {persona_name}")
            else:
                logger.error(f"❌ Failed to generate semantic map for {persona_name}: {output}")
        
        # Update execution status
        all_success = all(r["success"] for r in results)
        execution_store[execution_id].status = "completed" if all_success else "failed"
        execution_store[execution_id].result = {
            "results": results,
            "total_personas": len(personas),
            "successful": sum(1 for r in results if r["success"]),
            "failed": sum(1 for r in results if not r["success"])
        }
        execution_store[execution_id].completed_at = datetime.now()
        
        if not all_success:
            failed_personas = [r["persona"] for r in results if not r["success"]]
            execution_store[execution_id].error = f"Failed for personas: {', '.join(failed_personas)}"
        
    except Exception as e:
        execution_store[execution_id].status = "failed"
        execution_store[execution_id].error = str(e)
        execution_store[execution_id].completed_at = datetime.now()
        logger.error(f"Error regenerating semantic maps: {e}")
        logger.error(traceback.format_exc())


@app.get("/api/projects/{project_id}/tasks", response_model=List[TaskInfo])
async def get_project_tasks(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get all tasks for a project.
    
    Currently returns all file-based tasks from the tasks directory.
    Tasks are stored as .md files and parsed on-the-fly.
    Future: Will integrate with Jira and sync tasks to database.
    """
    try:
        # For now, return all file-based tasks
        # TODO: When Jira integration is added, filter tasks by project_id
        task_files = get_task_files()
        tasks = [parse_task_file(f) for f in task_files]
        
        # Add project_id to each task for consistency
        for task in tasks:
            task["project_id"] = project_id
        
        return tasks
    except Exception as e:
        logger.error(f"Error getting project tasks: {e}")
        return []


@app.post("/api/tasks", response_model=TaskInfo)
async def create_task(task_data: TaskCreate, db: AsyncSession = Depends(get_db)):
    """Create a new task."""
    try:
        project_uuid = UUID(task_data.project_id)
        
        # Verify project exists
        project_result = await db.execute(select(Project).where(Project.id == project_uuid))
        project = project_result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {task_data.project_id} not found")
        
        # Generate file_path if not provided
        file_path = task_data.file_path
        if not file_path:
            mapper_dir = Path(__file__).parent.parent.parent
            tasks_dir = mapper_dir / "tasks"
            tasks_dir.mkdir(exist_ok=True)
            
            # Generate filename from title
            safe_title = "".join(c if c.isalnum() or c in (' ', '-', '_') else '' for c in task_data.title)
            safe_title = safe_title.replace(' ', '_').lower()[:50]
            file_path = f"tasks/{safe_title}_task.md"
        
        task = Task(
            project_id=project_uuid,
            title=task_data.title,
            description=task_data.description,
            pr_link=task_data.pr_link,
            file_path=file_path,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        
        # Create the task.md file if it doesn't exist
        if file_path:
            mapper_dir = Path(__file__).parent.parent.parent
            task_file = mapper_dir / file_path
            if not task_file.exists():
                task_file.parent.mkdir(parents=True, exist_ok=True)
                task_file.write_text(f"# {task_data.title}\n\n## Description\n\n{task_data.description}\n\n## PR Link\n\n{task_data.pr_link or 'N/A'}\n")
        
        return TaskInfo(**task.to_dict())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid project ID: {task_data.project_id}")
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/tasks/{task_id}", response_model=TaskInfo)
async def update_task(
    task_id: str,
    task_data: TaskUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a task."""
    try:
        task_uuid = UUID(task_id)
        result = await db.execute(select(Task).where(Task.id == task_uuid))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        # Update fields
        update_data = task_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(task, key, value)
        
        task.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(task)
        
        # Update the task.md file if file_path exists
        if task.file_path:
            mapper_dir = Path(__file__).parent.parent.parent
            task_file = mapper_dir / task.file_path
            if task_file.exists():
                content = f"# {task.title}\n\n## Description\n\n{task.description}\n\n## PR Link\n\n{task.pr_link or 'N/A'}\n"
                task_file.write_text(content)
        
        return TaskInfo(**task.to_dict())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid task ID: {task_id}")
    except Exception as e:
        logger.error(f"Error updating task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a task."""
    try:
        task_uuid = UUID(task_id)
        result = await db.execute(select(Task).where(Task.id == task_uuid))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        file_path = task.file_path
        await db.delete(task)
        await db.commit()
        
        # Optionally delete the task.md file
        # (commented out to preserve files - uncomment if desired)
        # if file_path:
        #     mapper_dir = Path(__file__).parent.parent.parent
        #     task_file = mapper_dir / file_path
        #     if task_file.exists():
        #         task_file.unlink()
        
        return {"message": f"Task {task_id} deleted successfully"}
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid task ID: {task_id}")
    except Exception as e:
        logger.error(f"Error deleting task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        elif 'PR Link' in line or 'pr_link' in line.lower() or '## PR Link' in line or line.strip().lower() == 'pr:':
            # Try to extract PR link from this line or next few lines
            for j in range(i, min(i + 3, len(lines))):
                if 'http' in lines[j]:
                    # Extract just the URL (handle cases like "PR: https://..." or just "https://...")
                    url_match = re.search(r'(https?://[^\s]+)', lines[j])
                    if url_match:
                        pr_link = url_match.group(1)
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
    """List all available tasks.
    
    Tasks are loaded from markdown files in the tasks directory.
    See TASK_MANAGEMENT.md for details on task file format.
    """
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


async def run_semantic_mapper(task_id: str, execution_id: str, project_config: Optional[Dict[str, Any]] = None):
    """Run semantic mapper in background."""
    try:
        execution_store[execution_id].status = "running"
        
        mapper_dir = Path(__file__).parent.parent.parent
        script_path = mapper_dir / "semantic_mapper.py"
        graph_file = mapper_dir / "semantic_graph.json"
        
        # Prepare environment with project config
        env = os.environ.copy()
        if project_config:
            env["PROJECT_BASE_URL"] = project_config.get("BASE_URL", "")
            env["PROJECT_API_BASE"] = project_config.get("API_BASE", "")
            env["PROJECT_BACKEND_PATH"] = project_config.get("BACKEND_PATH", "")
            # Extract persona names from persona objects
            personas = project_config.get("PERSONAS", [])
            if personas:
                persona_names = []
                for p in personas:
                    if isinstance(p, dict):
                        persona_names.append(p.get("name", ""))
                    elif isinstance(p, str):
                        # Legacy format
                        persona_names.append(p)
                if persona_names:
                    env["PROJECT_PERSONAS"] = ",".join(persona_names)
                    # Also store full persona objects as JSON for gateway instructions access
                    env["PROJECT_PERSONAS_FULL"] = json.dumps(personas)
        
        # Run semantic mapper
        process = await asyncio.create_subprocess_exec(
            "uv", "run", "python", str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # Combine stderr with stdout
            cwd=str(mapper_dir),
            env=env
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


async def run_context_processor(task_id: str, execution_id: str, project_config: Optional[Dict[str, Any]] = None):
    """Run context processor to generate mission.json."""
    try:
        execution_store[execution_id].status = "running"
        
        mapper_dir = Path(__file__).parent.parent.parent
        script_path = mapper_dir / "context_processor.py"
        
        # Prepare environment with project config
        env = os.environ.copy()
        if project_config:
            env["PROJECT_BASE_URL"] = project_config.get("BASE_URL", "")
            env["PROJECT_API_BASE"] = project_config.get("API_BASE", "")
            env["PROJECT_DATABASE_URL"] = project_config.get("DATABASE_URL", "")
            env["PROJECT_OPENAPI_URL"] = project_config.get("OPENAPI_URL", "")
            env["PROJECT_BACKEND_PATH"] = project_config.get("BACKEND_PATH", "")
            # Extract persona names and store full objects for gateway instructions
            personas = project_config.get("PERSONAS", [])
            if personas:
                persona_names = []
                for p in personas:
                    if isinstance(p, dict):
                        persona_names.append(p.get("name", ""))
                    elif isinstance(p, str):
                        persona_names.append(p)
                if persona_names:
                    env["PROJECT_PERSONAS"] = ",".join(persona_names)
                    env["PROJECT_PERSONAS_FULL"] = json.dumps(personas)
        
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
        
        # Determine the correct semantic graph to use
        # Priority: 1. First persona from project config, 2. Look for any persona graph, 3. Default
        graph_file = "semantic_graph.json"  # Default
        
        if project_config:
            personas = project_config.get("PERSONAS", [])
            if personas:
                # Get first persona name
                first_persona = personas[0]
                if isinstance(first_persona, dict):
                    persona_name = first_persona.get("name", "")
                else:
                    persona_name = first_persona
                
                if persona_name:
                    # Check if persona-specific graph exists (case-insensitive)
                    for graph_path in mapper_dir.glob("semantic_graph_*.json"):
                        if persona_name.lower() in graph_path.name.lower():
                            graph_file = graph_path.name
                            logger.info(f"Using persona-specific graph: {graph_file}")
                            break
        
        # Fallback: if no persona graph found, check if any persona graph exists
        if graph_file == "semantic_graph.json":
            persona_graphs = list(mapper_dir.glob("semantic_graph_*.json"))
            if persona_graphs:
                # Use the most recently modified one
                persona_graphs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                graph_file = persona_graphs[0].name
                logger.info(f"Using most recent persona graph: {graph_file}")
        
        # Run context processor with the specific task file and graph
        cmd = ["uv", "run", "python", str(script_path), str(task_file_path), "--graph", graph_file]
        logger.info(f"Running context processor: {' '.join(cmd)}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # Combine stderr with stdout
            cwd=str(mapper_dir),
            env=env
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


async def run_executor(task_id: str, execution_id: str, mission_file: Optional[str] = None, project_config: Optional[Dict[str, Any]] = None):
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
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        
        # Add project config to environment
        if project_config:
            env["PROJECT_BASE_URL"] = project_config.get("BASE_URL", "")
            env["PROJECT_API_BASE"] = project_config.get("API_BASE", "")
            env["PROJECT_DATABASE_URL"] = project_config.get("DATABASE_URL", "")
            # Keep existing DATABASE_URL if PROJECT_DATABASE_URL not set
            if not env.get("PROJECT_DATABASE_URL") and env.get("DATABASE_URL"):
                pass  # Use existing DATABASE_URL
            elif env.get("PROJECT_DATABASE_URL"):
                env["DATABASE_URL"] = env["PROJECT_DATABASE_URL"]
            # Extract persona names and store full objects for gateway instructions
            personas = project_config.get("PERSONAS", [])
            if personas:
                persona_names = []
                for p in personas:
                    if isinstance(p, dict):
                        persona_names.append(p.get("name", ""))
                    elif isinstance(p, str):
                        persona_names.append(p)
                if persona_names:
                    env["PROJECT_PERSONAS"] = ",".join(persona_names)
                    env["PROJECT_PERSONAS_FULL"] = json.dumps(personas)
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
    background_tasks: BackgroundTasks,
    project_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Run a task operation (map, generate-mission, or execute)."""
    try:
        execution_id = str(uuid.uuid4())
        
        # Load project config if project_id provided
        project_config = None
        if project_id:
            from .project_config import load_project_config, get_config_for_execution
            project_config = await load_project_config(project_id, db)
            if project_config:
                project_config = get_config_for_execution(project_config)
        
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
        
        # Run appropriate operation in background (pass project_config via options)
        options = request.options or {}
        if project_config:
            options["project_config"] = project_config
        if project_id:
            options["project_id"] = project_id
        
        if request.operation == "map":
            background_tasks.add_task(run_semantic_mapper, task_id, execution_id, project_config)
        elif request.operation == "generate-mission":
            background_tasks.add_task(run_context_processor, task_id, execution_id, project_config)
        elif request.operation == "execute":
            mission_file = options.get("mission_file")
            background_tasks.add_task(run_executor, task_id, execution_id, mission_file, project_config)
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
async def get_semantic_graph(
    persona: Optional[str] = None, 
    project_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get the semantic graph JSON.
    
    Args:
        persona: Optional persona name to load persona-specific graph (e.g., 'reseller')
        project_id: Optional project ID - if provided and persona not specified, 
                   will try to load graph for the first persona in the project
    """
    try:
        mapper_dir = Path(__file__).parent.parent.parent
        
        # Determine which graph file to load
        graph_file = None
        
        def find_graph_file(persona_name: str) -> Optional[Path]:
            """Find graph file case-insensitively."""
            if not persona_name:
                return None
            
            # Try exact match first
            exact_file = mapper_dir / f"semantic_graph_{persona_name}.json"
            if exact_file.exists():
                logger.info(f"Found exact match for persona '{persona_name}': {exact_file.name}")
                return exact_file
            
            # Try case-insensitive search
            target_name_lower = f"semantic_graph_{persona_name.lower()}.json"
            available_files = list(mapper_dir.glob("semantic_graph_*.json"))
            logger.info(f"Searching for persona '{persona_name}' (target: {target_name_lower})")
            logger.info(f"Available graph files: {[f.name for f in available_files]}")
            
            for file_path in available_files:
                if file_path.name.lower() == target_name_lower:
                    logger.info(f"Found case-insensitive match: {file_path.name}")
                    return file_path
            
            logger.warning(f"No graph file found for persona '{persona_name}'")
            return None
        
        if persona:
            # Load persona-specific graph (case-insensitive)
            graph_file = find_graph_file(persona)
        elif project_id:
            # Try to get the first persona from the project
            try:
                from uuid import UUID
                project_uuid = UUID(project_id)
                result = await db.execute(select(Project).where(Project.id == project_uuid))
                project = result.scalar_one_or_none()
                
                if project and project.personas:
                    # Get first persona name
                    first_persona = project.personas[0]
                    if isinstance(first_persona, dict):
                        persona_name = first_persona.get("name", "")
                    else:
                        persona_name = str(first_persona)
                    
                    if persona_name:
                        graph_file = find_graph_file(persona_name)
                        logger.info(f"Loading graph for project {project_id}, persona: {persona_name}")
            except Exception as e:
                logger.warning(f"Could not load project {project_id} to determine persona: {e}")
        
        # Fallback to default graph if persona-specific not found
        if not graph_file or not graph_file.exists():
            graph_file = mapper_dir / "semantic_graph.json"
        
        if not graph_file.exists():
            raise HTTPException(
                status_code=404, 
                detail=f"Semantic graph not found: {graph_file.name}. Run semantic mapper first."
            )
        
        logger.info(f"Loading semantic graph from: {graph_file}")
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
    background_tasks: BackgroundTasks,
    project_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Run automated workflow: intelligently run Map → Generate Mission → Execute."""
    try:
        execution_id = str(uuid.uuid4())
        
        # Load project config if project_id provided
        project_config = None
        if project_id:
            from .project_config import load_project_config, get_config_for_execution
            project_config = await load_project_config(project_id, db)
            if project_config:
                project_config = get_config_for_execution(project_config)
        
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
                
                orchestrator = AgentOrchestrator(
                    update_callback=update_callback,
                    project_id=project_id,
                    project_config=project_config
                )
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
