"""SQLAlchemy database models for projects and tasks."""
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import Column, String, Text, ForeignKey, JSON, DateTime, UniqueConstraint, Integer
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
    test_clusters = relationship("TestCluster", back_populates="project", cascade="all, delete-orphan")
    selector_corrections = relationship("SelectorCorrection", back_populates="project", cascade="all, delete-orphan")

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
    test_clusters = relationship("TestCluster", back_populates="task")

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


class TestCluster(Base):
    """TestCluster model - represents a test case and its cluster assignment."""
    __tablename__ = "test_clusters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    cluster_name = Column(String(255), nullable=False)  # e.g., "auth", "sales_bookings"
    test_case_id = Column(String(255), nullable=False)  # e.g., "verify_tcv_column_reseller"
    target_node = Column(String(255), nullable=False)   # Links to semantic_graph node
    purpose = Column(Text, nullable=True)
    mission_file = Column(String(500), nullable=True)
    status = Column(String(50), default="active", nullable=False)  # active, deprecated, conflicting
    extra_data = Column(JSONB, default=dict)  # Additional metadata (persona, verification points, etc.)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    project = relationship("Project", back_populates="test_clusters")
    task = relationship("Task", back_populates="test_clusters")

    def to_dict(self) -> dict:
        """Convert test cluster to dictionary."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "task_id": str(self.task_id) if self.task_id else None,
            "cluster_name": self.cluster_name,
            "test_case_id": self.test_case_id,
            "target_node": self.target_node,
            "purpose": self.purpose,
            "mission_file": self.mission_file,
            "status": self.status,
            "extra_data": self.extra_data or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SelectorCorrection(Base):
    """SelectorCorrection model - stores JIT selector resolutions for learning."""
    __tablename__ = "selector_corrections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(String(255), nullable=False)      # semantic_graph node ID
    component_role = Column(String(255), nullable=True)
    original_selector = Column(Text, nullable=False)
    corrected_selector = Column(Text, nullable=False)
    action_type = Column(String(50), nullable=True)    # click, fill, wait_visible
    context = Column(JSONB, default=dict)              # Additional context (description, step, etc.)
    success_count = Column(Integer, default=1, nullable=False)  # Track reliability
    last_used_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    project = relationship("Project", back_populates="selector_corrections")

    __table_args__ = (
        UniqueConstraint("project_id", "node_id", "original_selector", name="uq_selector_correction_original"),
    )

    def to_dict(self) -> dict:
        """Convert selector correction to dictionary."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "node_id": self.node_id,
            "component_role": self.component_role,
            "original_selector": self.original_selector,
            "corrected_selector": self.corrected_selector,
            "action_type": self.action_type,
            "context": self.context or {},
            "success_count": self.success_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
