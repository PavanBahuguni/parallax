# Tasks Directory

This directory contains all task definition files in markdown format.

## File Naming Convention

- `task.md` - Default task (will be treated as TASK-1)
- `TASK-1_task.md` - Explicit TASK-1 definition
- `TASK-2_task.md` - TASK-2 definition
- `TASK-N_task.md` - TASK-N definition

## Task File Format

Each task file should follow this structure:

```markdown
# TASK-X: Task Title

## Description
Detailed description of the task...

## Changes Required
- Database changes
- Backend changes
- Frontend changes

## Test Requirements
### Database Layer
- Requirements

### API Layer
- Requirements

### UI Layer
- Requirements

## PR Link
https://github.com/user/repo/pull/X

## Expected Behavior
What should happen when the test runs...

## Triple-Check Verification Points
- DB Check: ...
- API Check: ...
- UI Check: ...
```

## Usage

The dashboard will automatically discover all `.md` files in this directory and display them as tasks. When you click "Generate Mission" for a task, the context processor will:

1. Read the task file
2. Extract intent and PR information
3. Match with semantic graph
4. Generate `temp/{TASK-ID}_mission.json`
