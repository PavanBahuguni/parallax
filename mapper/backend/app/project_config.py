"""Project configuration loading and injection."""
from typing import Dict, Optional, Any, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .models import Project, ProjectConfig


async def load_project_config(project_id: str, db: AsyncSession) -> Optional[Dict[str, Any]]:
    """Load project configuration from database.
    
    Args:
        project_id: Project UUID as string
        db: Database session
        
    Returns:
        Dict with project configuration or None if not found
    """
    try:
        project_uuid = UUID(project_id)
        result = await db.execute(select(Project).where(Project.id == project_uuid))
        project = result.scalar_one_or_none()
        
        if not project:
            return None
        
        # Load additional configs from project_configs table
        configs_result = await db.execute(
            select(ProjectConfig).where(ProjectConfig.project_id == project_uuid)
        )
        configs = configs_result.scalars().all()
        config_dict = {cfg.config_key: cfg.config_value for cfg in configs}
        
        # Build configuration dict
        config = {
            "project_id": str(project.id),
            "project_name": project.name,
            "BASE_URL": project.ui_url,
            "API_BASE": project.api_base_url or "",
            "OPENAPI_URL": project.openapi_url,
            "DATABASE_URL": project.database_url,
            "BACKEND_PATH": project.backend_path,
            "PERSONAS": project.personas or [],  # List of persona objects: [{"name": "...", "gateway_instructions": "..."}]
            # Merge additional configs
            **config_dict
        }
        
        return config
        
    except Exception as e:
        print(f"Error loading project config: {e}")
        return None


def get_config_for_execution(config: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare configuration for execution scripts.
    
    Converts project config to format expected by semantic_mapper, context_processor, executor.
    
    Args:
        config: Project configuration dict
        
    Returns:
        Execution-ready config dict
    """
    return {
        "BASE_URL": config.get("BASE_URL", "http://localhost:5173"),
        "API_BASE": config.get("API_BASE", "http://localhost:8000"),
        "OPENAPI_URL": config.get("OPENAPI_URL"),
        "DATABASE_URL": config.get("DATABASE_URL"),
        "BACKEND_PATH": config.get("BACKEND_PATH"),
        "PERSONAS": config.get("PERSONAS", []),  # List of persona objects with gateway_instructions
        "PROJECT_ID": config.get("project_id"),
        "PROJECT_NAME": config.get("project_name"),
    }


def get_persona_gateway_instructions(personas: List[Dict[str, Any]], persona_name: str) -> Optional[str]:
    """Get gateway instructions for a specific persona.
    
    Args:
        personas: List of persona objects from project config
        persona_name: Name of the persona to get instructions for
        
    Returns:
        Gateway instructions string or None if not found
    """
    for persona in personas:
        if isinstance(persona, dict) and persona.get("name") == persona_name:
            return persona.get("gateway_instructions", "")
        elif isinstance(persona, str) and persona == persona_name:
            # Legacy format - no instructions
            return ""
    return None


async def get_default_project_config(db: AsyncSession) -> Optional[Dict[str, Any]]:
    """Get default project configuration (for backward compatibility).
    
    Returns the first project or creates a default one.
    
    Args:
        db: Database session
        
    Returns:
        Default project config or None
    """
    try:
        # Try to get first project
        result = await db.execute(select(Project).limit(1))
        project = result.scalar_one_or_none()
        
        if project:
            return await load_project_config(str(project.id), db)
        
        # No projects exist - return None (caller should handle)
        return None
        
    except Exception as e:
        print(f"Error getting default project: {e}")
        return None
