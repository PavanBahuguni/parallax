# Database Setup Guide

The Agentic QA system uses PostgreSQL to store project configurations and tasks. We use **Alembic** for database migrations.

## Quick Setup

Run the setup script to create the database and run Alembic migrations:

```bash
cd mapper/backend
uv run python scripts/setup_database.py
```

This script will:
1. Connect to your PostgreSQL server
2. Create the `agentic_qa` database if it doesn't exist
3. Run Alembic migrations to create all tables

## Using Alembic Directly

If you prefer to use Alembic commands directly:

### 1. Create the Database Manually

```bash
psql -U postgres
CREATE DATABASE agentic_qa;
\q
```

### 2. Run Alembic Migrations

```bash
cd mapper/backend
uv run alembic upgrade head
```

This will create all tables defined in the migration files.

### Other Alembic Commands

- **Check current migration status**: `uv run alembic current`
- **Show migration history**: `uv run alembic history`
- **Create a new migration**: `uv run alembic revision --autogenerate -m "description"`
- **Downgrade one migration**: `uv run alembic downgrade -1`
- **Upgrade to specific revision**: `uv run alembic upgrade <revision>`

## Manual Setup

If you prefer to set up the database manually:

### 1. Create the Database

Connect to PostgreSQL and create the database:

```bash
psql -U postgres
CREATE DATABASE agentic_qa;
\q
```

### 2. Configure Database URL

Set the `DATABASE_URL` environment variable in `mapper/.env`:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/agentic_qa
```

Replace `postgres:postgres` with your actual PostgreSQL username and password.

### 3. Run Migrations

```bash
cd mapper/backend
uv run alembic upgrade head
```

## Troubleshooting

### Database "agentic_qa" does not exist

If you see this error, run the setup script:

```bash
cd mapper/backend
uv run python scripts/setup_database.py
```

### Connection Refused

Make sure PostgreSQL is running:

```bash
# macOS (Homebrew)
brew services start postgresql

# Linux (systemd)
sudo systemctl start postgresql

# Docker
docker run -d --name postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres
```

### Authentication Failed

Check your PostgreSQL username and password in the `DATABASE_URL` environment variable.

## Default Configuration

The default database configuration is:
- **Host**: localhost
- **Port**: 5432
- **Database**: agentic_qa
- **User**: postgres
- **Password**: postgres

You can override these by setting the `DATABASE_URL` environment variable.
