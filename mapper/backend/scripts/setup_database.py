"""Script to create the database if it doesn't exist."""
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from dotenv import load_dotenv

# Load environment
mapper_dir = Path(__file__).parent.parent.parent
env_file = mapper_dir / ".env"
if env_file.exists():
    load_dotenv(env_file)


async def create_database():
    """Create the database if it doesn't exist."""
    # Get database URL from environment
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/agentic_qa"
    )
    
    # Parse the URL to extract components
    # Format: postgresql://user:password@host:port/dbname
    if "://" not in database_url:
        print(f"❌ Invalid DATABASE_URL format: {database_url}")
        return False
    
    # Remove postgresql+asyncpg:// prefix if present
    url_without_prefix = database_url.replace("postgresql+asyncpg://", "postgresql://")
    
    # Parse URL
    parts = url_without_prefix.replace("postgresql://", "").split("@")
    if len(parts) != 2:
        print(f"❌ Invalid DATABASE_URL format: {database_url}")
        return False
    
    auth_part, host_db_part = parts
    user_pass = auth_part.split(":")
    if len(user_pass) == 2:
        user, password = user_pass
    else:
        user = user_pass[0]
        password = None
    
    host_port_db = host_db_part.split("/")
    if len(host_port_db) != 2:
        print(f"❌ Invalid DATABASE_URL format: {database_url}")
        return False
    
    host_port = host_port_db[0]
    db_name = host_port_db[1]
    
    if ":" in host_port:
        host, port = host_port.split(":")
    else:
        host = host_port
        port = "5432"
    
    print(f"📊 Database Configuration:")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   User: {user}")
    print(f"   Database: {db_name}")
    
    # Connect to postgres database to create the target database
    postgres_url = f"postgresql://{user}"
    if password:
        postgres_url += f":{password}"
    postgres_url += f"@{host}:{port}/postgres"
    
    try:
        print(f"\n🔌 Connecting to PostgreSQL server...")
        conn = await asyncpg.connect(postgres_url)
        
        # Check if database exists
        db_exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        
        if db_exists:
            print(f"✅ Database '{db_name}' already exists")
            await conn.close()
            return True
        
        # Create database
        print(f"📝 Creating database '{db_name}'...")
        # Note: CREATE DATABASE cannot be run in a transaction
        await conn.execute(f'CREATE DATABASE "{db_name}"')
        await conn.close()
        
        print(f"✅ Database '{db_name}' created successfully!")
        return True
        
    except asyncpg.exceptions.InvalidPasswordError:
        print(f"❌ Authentication failed. Please check your username and password.")
        return False
    except asyncpg.exceptions.ConnectionRefusedError:
        print(f"❌ Could not connect to PostgreSQL server at {host}:{port}")
        print(f"   Make sure PostgreSQL is running and accessible.")
        return False
    except Exception as e:
        print(f"❌ Error creating database: {e}")
        return False


async def run_migrations():
    """Run Alembic migrations to create tables."""
    import subprocess
    
    print(f"\n🔄 Running Alembic migrations...")
    backend_dir = Path(__file__).parent.parent
    
    try:
        # Run alembic upgrade head
        print("   Running: uv run alembic upgrade head")
        result = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=str(backend_dir),
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Alembic migrations completed successfully!")
            if result.stdout:
                print(result.stdout)
            return True
        else:
            print(f"❌ Alembic migration failed:")
            if result.stderr:
                print(result.stderr)
            if result.stdout:
                print(result.stdout)
            return False
            
    except Exception as e:
        print(f"❌ Error running Alembic migrations: {e}")
        return False


async def main():
    """Main function."""
    print("🚀 Setting up database for Agentic QA...\n")
    
    # Create database
    db_created = await create_database()
    if not db_created:
        print("\n❌ Database setup failed. Please fix the errors above and try again.")
        sys.exit(1)
    
    # Run migrations
    migrations_success = await run_migrations()
    if not migrations_success:
        print("\n⚠️  Database created but migrations failed. You may need to run migrations manually:")
        print("   cd mapper/backend")
        print("   uv run alembic upgrade head")
        sys.exit(1)
    
    print("\n✅ Database setup complete!")
    print("\nYou can now start the backend server and use the project management features.")


if __name__ == "__main__":
    asyncio.run(main())
