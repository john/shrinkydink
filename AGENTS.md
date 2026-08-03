<!-- shrinkydink:start -->
## Repository context hygiene

- Treat `.agentsignore` as an agent-specific exclusion list using gitignore-style patterns. Do not read, search, summarize, index, or attach matching content unless the user explicitly requests it or it is indispensable to the task.
- In `warn` mode, an explicit user request may justify a documented exception. In `deny` mode, stop and ask the user to change `.shrinkydink.json` to `warn` before accessing a matched path.
- When an exception is necessary, explain why and inspect the narrowest possible file, range, or command output. Never reveal secret values from ignored files.
- Prefer targeted symbol search, path-scoped search, and bounded reads over recursive repository ingestion. Summarize discoveries with exact file paths and symbols, then discard bulky raw output.
- Do not load generated files, dependency trees, caches, archives, databases, source maps, or minified bundles when source files or targeted queries are available.
- When the interface reports context usage at or above 70% (30% remaining), warn the user and recommend checkpointing work and starting a new session at the next clean boundary.
- Before a new session, leave a compact handoff containing: objective, key decisions, changed files, verification performed, unresolved issues, and the next command or action.
- Treat `.agentsignore` hooks as guardrails, not proof of isolation. Follow these rules even when a tool path bypasses hooks.
<!-- shrinkydink:end -->
