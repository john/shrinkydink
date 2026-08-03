# Platform support and limits

## Shared instruction architecture

`AGENTS.md` is the canonical shared instruction file. Codex reads it natively. Claude Code reads `CLAUDE.md`, so shrinkydink places `@AGENTS.md` in `CLAUDE.md` and keeps Claude-specific notes below the import. This avoids maintaining two divergent copies of the same rules.

## Claude Code

Shrinkydink configures `.claude/settings.local.json` with:

- `respectGitignore: true` when the setting is absent;
- a `PreToolUse` command hook for file-oriented tools and Bash;
- a status-line command that reads `context_window.used_percentage` and warns at the configured threshold.

An existing status line is preserved because Claude supports one status-line command per active setting layer and arbitrary composition is unsafe. In that case, the audit reports a manual integration warning.

Claude PreToolUse does not run for files inserted directly with `@path`. A hard security boundary requires native permission-deny rules or an external sandbox; `.agentsignore` is not sufficient.

## OpenAI Codex

Shrinkydink configures project-local Codex hooks in `.codex/hooks.json`, unless the existing project config already uses inline hooks. It adds:

- `PreToolUse` for advisory or denying `.agentsignore` checks;
- `PreCompact` for a visible checkpoint/new-session warning.

It also ensures the TUI status line includes `context-remaining`. Codex currently exposes a native remaining-context footer and compaction lifecycle event, but not a project-hook field containing the exact context percentage. Therefore the configured numeric threshold is exact in Claude and advisory in Codex: Codex shows remaining context continuously and warns when compaction begins.

Project-local Codex hooks require the repository's `.codex` layer and hook definitions to be trusted. A changed hook may require review again.

## Cross-agent ignore file

The configured `agentsignore` file (default `.agentsignore`) is a shrinkydink
convention, not a universal agent standard. It is honored through three layers:

1. written instructions in `AGENTS.md` and imported `CLAUDE.md`;
2. lifecycle hooks that inspect common path-bearing tool inputs;
3. narrow default patterns that exclude dependencies, caches, generated output, secrets, archives, and binary databases.

The guard can miss indirect shell expansion, tool-specific arguments it does not recognize, hosted tools, direct prompt attachments, and agent implementations that ignore both `AGENTS.md` and lifecycle hooks. Default to `warn`; use `deny` only as defense in depth, not as a substitute for filesystem permissions, secret management, or sandboxing.

The guard distinguishes many narrow path-scoped searches from repository-wide scans. A command such as `rg term src/` normally proceeds without a broad-search warning, while an unscoped repository search may warn because it can traverse ignored paths. This detection is intentionally conservative and remains best-effort.

## Runtime assumptions

The generated helpers require Python 3 and use only the standard library. Python
3.11+ additionally enables parse validation of existing and generated Codex TOML
through `tomllib`. The guard discovers a root using `.git` or
`.shrinkydink.json`, so a configured ignore path also works in a non-Git
directory. POSIX hook commands resolve the Git top level before invoking them.
Windows command overrides are included for Codex, but repositories opened from
nested directories should be tested because Windows shell and Python-launcher
behavior varies. WSL or Git Bash provides the most consistent cross-platform
behavior.
