"""Migration script to create default project and associate existing tasks."""
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, text
from app.models import Project, Task, Base
from app.database import DATABASE_URL


async def migrate():
    """Create default project and migrate existing tasks."""
    # Create engine
    engine = create_async_engine(DATABASE_URL, echo=True)
    
    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create session
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    
    async with AsyncSessionLocal() as session:
        try:
            # Check if default project already exists
            result = await session.execute(
                select(Project).where(Project.name == "Default Project")
            )
            default_project = result.scalar_one_or_none()
            
            if not default_project:
                # Create default project with current hardcoded values
                print("Creating default project...")
                default_project = Project(
                    name="Default Project",
                    description="Default project for existing tasks",
                    ui_url=os.getenv("BASE_URL", "http://localhost:5173"),
                    api_base_url=os.getenv("API_BASE", "http://localhost:8000"),
                    database_url=os.getenv("DATABASE_URL"),
                    backend_path=os.getenv("BACKEND_PATH", "../sample-app/backend"),
                    personas=[],
                )
                session.add(default_project)
                await session.commit()
                await session.refresh(default_project)
                print(f"✅ Created default project: {default_project.id}")
            else:
                print(f"✅ Default project already exists: {default_project.id}")
            
            # Migrate existing tasks from file system
            mapper_dir = Path(__file__).parent.parent.parent
            tasks_dir = mapper_dir / "tasks"
            
            if tasks_dir.exists():
                task_files = list(tasks_dir.glob("*.md"))
                print(f"\nFound {len(task_files)} task file(s)")
                
                for task_file in task_files:
                    # Parse task file to get basic info
                    content = task_file.read_text()
                    lines = content.split('\n')
                    
                    title = "Unknown Task"
                    description = ""
                    pr_link = None
                    
                    for i, line in enumerate(lines):
                        if line.startswith('# '):
                            title = line[2:].strip()
                        elif line.startswith('## Description'):
                            desc_lines = []
                            for j in range(i + 1, len(lines)):
                                if lines[j].startswith('##'):
                                    break
                                desc_lines.append(lines[j])
                            description = '\n'.join(desc_lines).strip()
                        elif 'PR' in line or 'pr' in line.lower():
                            # Try to extract PR link
                            import re
                            pr_match = re.search(r'https?://[^\s]+', line)
                            if pr_match:
                                pr_link = pr_match.group(0)
                    
                    # Extract task ID from filename or generate one
                    task_id_from_file = task_file.stem.replace('_task', '').replace('TASK-', 'TASK-')
                    if not task_id_from_file.startswith('TASK-'):
                        task_id_from_file = f"TASK-{task_file.stem}"
                    
                    # Check if task already exists in DB
                    # For now, we'll create tasks based on file system
                    # In a real migration, you'd want to check for duplicates
                    print(f"  - {task_id_from_file}: {title}")
                    
                    # Note: We're not creating Task records here because tasks are currently
                    # file-based. The migration is mainly to create the default project.
                    # Tasks will be created in the database when they're first accessed via the API.
            
            print("\n✅ Migration complete!")
            print(f"Default project ID: {default_project.id}")
            print(f"Default project UI URL: {default_project.ui_url}")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            import traceback
            traceback.print_exc()
            await session.rollback()
            raise
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
