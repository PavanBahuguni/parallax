"""Pydantic schemas for API responses."""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel


class TaskInfo(BaseModel):
    """Task information from task.md file."""
    id: str
    title: str
    description: str
    pr_link: Optional[str] = None
    file_path: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ExecutionStatus(BaseModel):
    """Execution status information."""
    execution_id: str
    task_id: str
    status: str  # "running", "completed", "failed", "pending"
    started_at: datetime
    completed_at: Optional[datetime] = None
    execution_type: str  # "map", "generate-mission", "execute"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ExecutionResult(BaseModel):
    """Detailed execution result."""
    execution_id: str
    task_id: str
    execution_type: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    result: Dict[str, Any]
    error: Optional[str] = None


class RunTaskRequest(BaseModel):
    """Request to run a task operation."""
    operation: str  # "map", "generate-mission", "execute"
    options: Optional[Dict[str, Any]] = None
