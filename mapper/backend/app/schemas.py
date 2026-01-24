"""Pydantic schemas for API responses."""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class PersonaInfo(BaseModel):
    """Schema for persona with gateway instructions."""
    name: str = Field(..., min_length=1, max_length=100)
    gateway_instructions: str = Field(default="", description="Step-by-step gateway instructions for this persona")


class ProjectCreate(BaseModel):
    """Schema for creating a project."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    ui_url: str = Field(..., min_length=1, max_length=500)
    api_base_url: Optional[str] = Field(None, max_length=500)
    openapi_url: Optional[str] = Field(None, max_length=500)
    database_url: Optional[str] = Field(None, max_length=500)
    backend_path: Optional[str] = Field(None, max_length=500)
    personas: List[PersonaInfo] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    ui_url: Optional[str] = Field(None, min_length=1, max_length=500)
    api_base_url: Optional[str] = Field(None, max_length=500)
    openapi_url: Optional[str] = Field(None, max_length=500)
    database_url: Optional[str] = Field(None, max_length=500)
    backend_path: Optional[str] = Field(None, max_length=500)
    personas: Optional[List[PersonaInfo]] = None


class ProjectInfo(BaseModel):
    """Project information."""
    id: str
    name: str
    description: Optional[str] = None
    ui_url: str
    api_base_url: Optional[str] = None
    openapi_url: Optional[str] = None
    database_url: Optional[str] = None
    backend_path: Optional[str] = None
    personas: List[PersonaInfo] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskCreate(BaseModel):
    """Schema for creating a task."""
    project_id: str
    title: str
    description: str
    pr_link: Optional[str] = None
    file_path: Optional[str] = None  # Optional - can be auto-generated


class TaskUpdate(BaseModel):
    """Schema for updating a task."""
    title: Optional[str] = None
    description: Optional[str] = None
    pr_link: Optional[str] = None
    file_path: Optional[str] = None


class TaskInfo(BaseModel):
    """Task information from task.md file."""
    id: str
    project_id: Optional[str] = None  # Added for project association
    title: str
    description: str
    pr_link: Optional[str] = None
    file_path: Optional[str] = None
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


class RegenerateSemanticMapsRequest(BaseModel):
    """Request to regenerate semantic maps."""
    headless: bool = Field(default=True, description="Run browser in headless mode (false to see browser)")
