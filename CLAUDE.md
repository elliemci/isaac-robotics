# Session Startup & Pre-Task Instructions

Before starting any new task, bug fix, or code generation:
1. **Sync with Remote**: Run `git pull origin main` to ensure the local branch has the latest upstream changes.
2. **Inspect Context & Recent Changes**: Check `git log -n 5 --stat` or `git status` to see recently committed files, ongoing changes, and existing project structure before writing new code.
3. **Avoid Duplication**: Verify whether requested helper functions, scripts, or assets already exist in the codebase before creating new ones.


# Git & Commit Rules

- **Auto-Commit on File Edits**: After writing or modifying any key file, run `git add <file>` and commit with a concise, descriptive commit message.
- **Auto-Push on Task Completion**: When a user request, bug fix, or task is fully completed, ensure all staged changes are committed and run `git push origin main`.
- **Ignore Build Artifacts**: Ensure build directories (`build/`, `install/`, `log/`) are never staged or committed.