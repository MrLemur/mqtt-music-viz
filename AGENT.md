# Agent Instructions

This file documents the responsibilities and workflow for the automated coding agent working in this repository.

Responsibilities

- Update the repository `TODO.md` and the managed todo list (`manage_todo_list`) when starting and completing tasks.
- Only mark one task as `in-progress` at a time.
- When a task is completed, immediately mark it `completed` and provide a concise progress update in the commit/PR description.
- Prefer small, focused commits and create feature branches per phase (e.g. `feature/phase-2-assets`).
- Run linters and type checks when making functional changes and report the results.
- Avoid changing external library files or vendored code. Only operate on project files.

Iteration Rules

- Before editing, read the target files and create a short plan of the edits.
- After editing, re-run quick checks (lint, basic smoke run) and report success/failures.
- If blocked, write a clear message describing the blocker and propose next steps.
