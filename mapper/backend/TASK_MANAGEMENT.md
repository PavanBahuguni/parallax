# Task Management

## Current Implementation

Tasks are currently loaded from **markdown files** in the `mapper/tasks/` directory.

### Task File Format

Tasks are stored as `.md` files with the following format:

```markdown
# TASK-2: Add Category Field

## Description

Add a category dropdown field to the product form.

## PR Link

https://github.com/owner/repo/pull/123
```

### Task File Locations

The system searches for task files in the following locations (in order):

1. **Primary**: `mapper/tasks/*.md` - All `.md` files in the tasks directory
2. **Legacy**: `mapper/task.md` - Root task file (backward compatibility)
3. **Legacy**: `mapper/TASK-*_task.md` - Task files in root (backward compatibility)
4. **Legacy**: `mapper/temp/*task*.md` - Task files in temp directory (backward compatibility)

### Task Parsing

Tasks are parsed automatically when:
- Listing tasks via `/api/tasks`
- Getting project tasks via `/api/projects/{project_id}/tasks`
- Running task operations

The parser extracts:
- **Task ID**: From filename or header (e.g., `TASK-2`)
- **Title**: First `# ` header line
- **Description**: Content under `## Description` section
- **PR Link**: Extracted from lines containing "PR Link" or "pr_link"

### Example Task File

Create a file `mapper/tasks/TASK-3_task.md`:

```markdown
# TASK-3: Implement User Authentication

## Description

Add user login and authentication functionality to the application.
Include password reset and email verification.

## PR Link

https://github.com/owner/repo/pull/456
```

## Future: Jira Integration

When Jira integration is added:

1. Tasks will be synced from Jira to the database
2. Tasks will still be stored as `.md` files for backward compatibility
3. The API will prioritize database tasks but fall back to file-based tasks
4. Task creation/updates will sync to both Jira and local files

## API Endpoints

### Get All Tasks
```
GET /api/tasks
```
Returns all tasks from file system.

### Get Project Tasks
```
GET /api/projects/{project_id}/tasks
```
Returns all file-based tasks (currently not filtered by project).

### Create Task (Future - for Jira sync)
```
POST /api/tasks
```
Will be used to sync tasks from Jira to database.

## Adding a New Task

To add a new task:

1. Create a new `.md` file in `mapper/tasks/` directory
2. Use the format shown above
3. The task will automatically appear in the project detail page
4. Refresh the page or click "Refresh" button

Example:
```bash
# Create a new task file
cat > mapper/tasks/TASK-4_task.md << 'EOF'
# TASK-4: Add Search Functionality

## Description

Implement search functionality for products with filters.

## PR Link

https://github.com/owner/repo/pull/789
EOF
```

The task will be automatically picked up by the system.
