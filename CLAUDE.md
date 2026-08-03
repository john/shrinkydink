<!-- shrinkydink:start -->
@AGENTS.md

## Claude Code integration

The shared repository instructions are imported from `AGENTS.md`. Committed `.claude/settings.json` provides the shared `.agentsignore` guard, conservative native secret-path denies, and the context-status command. Personal `.claude/settings.local.json` content is optional and preserved unless an exact Shrinkydink-managed entry can be migrated safely. Reload project settings and verify their source with `/status`; treat hook warnings as instructions to narrow the operation. An explicit user request may justify a documented exception when `ignore_mode` is `warn`.
<!-- shrinkydink:end -->
