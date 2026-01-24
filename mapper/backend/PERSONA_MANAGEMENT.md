# Persona Management

## Overview

Personas are managed through the **Project Configuration** in the UI and stored in the database. They are **not** read from markdown files.

## How Personas Work

### 1. **Storage**
- Personas are stored in the `projects` table in the database (`personas` column, JSONB type)
- Each project can have multiple personas (e.g., `["internal", "reseller", "distributor"]`)

### 2. **UI Management**
- **Create/Edit Project**: Use the Project Form to add personas
- **Format**: Comma-separated values (e.g., `internal, reseller, distributor`)
- **Location**: Project Detail Page → Edit Project → Personas field

### 3. **Usage in Execution**
When running tasks for a project:
1. Project config is loaded from database (includes personas)
2. Personas are passed via environment variable `PROJECT_PERSONAS` (comma-separated)
3. Semantic mapper and other scripts read personas from environment variables
4. Personas are used for:
   - Semantic graph generation (with gateway authentication)
   - Context processing
   - Test execution

## Example Flow

### Setting Personas via UI

1. Go to Projects page
2. Click "Add Project" or edit an existing project
3. In the "Personas" field, enter: `internal, reseller, distributor`
4. Save the project

### Using Personas in Execution

When you run a task for a project:
```python
# Backend loads project config
project_config = await load_project_config(project_id, db)
# project_config["PERSONAS"] = ["internal", "reseller", "distributor"]

# Passed to execution via environment
env["PROJECT_PERSONAS"] = ",".join(project_config["PERSONAS"])
# env["PROJECT_PERSONAS"] = "internal,reseller,distributor"

# Semantic mapper reads from environment
personas = os.getenv("PROJECT_PERSONAS", "").split(",")
# personas = ["internal", "reseller", "distributor"]
```

## Migration from Markdown Files

If you previously had personas in markdown files:
1. **Remove** persona references from `.md` files
2. **Add** personas to the project configuration via UI
3. Personas will be automatically used for all tasks in that project

## API

### Get Project Personas
```bash
GET /api/projects/{project_id}
# Response includes: "personas": ["internal", "reseller"]
```

### Update Project Personas
```bash
PUT /api/projects/{project_id}
{
  "personas": ["internal", "reseller", "distributor"]
}
```

## Notes

- Personas are **project-scoped** - each project has its own set of personas
- Personas are **optional** - projects can have zero personas
- Personas are used for **authentication** when using gateway-based semantic mapping
- The first persona in the list is typically used as the default for execution
