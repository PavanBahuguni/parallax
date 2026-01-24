"""SQLAlchemy database models for projects and tasks."""
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import Column, String, Text, ForeignKey, JSON, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Project(Base):
    """Project model - represents a configured application to test."""
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    ui_url = Column(String(500), nullable=False)  # e.g., http://localhost:5173
    api_base_url = Column(String(500), nullable=True)  # e.g., http://localhost:8000
    openapi_url = Column(String(500), nullable=True)  # e.g., https://api.example.com/openapi.json
    database_url = Column(String(500), nullable=True)  # e.g., postgresql://user:pass@host:port/db
    backend_path = Column(String(500), nullable=True)  # Path to backend code for DB schema parsing
    personas = Column(JSONB, default=list)  # Array of persona objects: [{"name": "reseller", "gateway_instructions": "..."}, ...]
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    configs = relationship("ProjectConfig", back_populates="project", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        """Convert project to dictionary."""
        # Convert personas from DB format (could be old string format or new object format)
        personas_list = []
        if self.personas:
            for p in self.personas:
                if isinstance(p, str):
                    # Legacy format: just a string
                    personas_list.append({"name": p, "gateway_instructions": ""})
                elif isinstance(p, dict):
                    # New format: object with name and gateway_instructions
                    personas_list.append({
                        "name": p.get("name", ""),
                        "gateway_instructions": p.get("gateway_instructions", "")
                    })
        
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "ui_url": self.ui_url,
            "api_base_url": self.api_base_url,
            "openapi_url": self.openapi_url,
            "database_url": self.database_url,
            "backend_path": self.backend_path,
            "personas": personas_list,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Task(Base):
    """Task model - represents a test task belonging to a project."""
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    pr_link = Column(String(500), nullable=True)
    file_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    project = relationship("Project", back_populates="tasks")

    def to_dict(self) -> dict:
        """Convert task to dictionary."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "title": self.title,
            "description": self.description,
            "pr_link": self.pr_link,
            "file_path": self.file_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ProjectConfig(Base):
    """ProjectConfig model - extensible key-value configuration for projects."""
    __tablename__ = "project_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    config_key = Column(String(255), nullable=False)
    config_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    project = relationship("Project", back_populates="configs")

    __table_args__ = (
        UniqueConstraint("project_id", "config_key", name="uq_project_config"),
    )

    def to_dict(self) -> dict:
        """Convert config to dictionary."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "config_key": self.config_key,
            "config_value": self.config_value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
