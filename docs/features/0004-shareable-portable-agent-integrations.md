# Shareable and portable agent integrations

## Outcome

A repository configured by Shrinkydink carries effective, reviewable guardrails for both Claude Code and OpenAI Codex when another developer clones it. Shared behavior no longer depends on an uncommitted Claude local settings file, and generated hook commands work from nested working directories on supported POSIX and Windows environments without overwriting personal preferences.

## Scope

### In scope

- Put team-shared Claude hooks and high-confidence native deny permissions in committed `.claude/settings.json` rather than relying on `.claude/settings.local.json`.
- Leave personal Claude configuration in `.claude/settings.local.json` untouched unless migrating entries that are unambiguously Shrinkydink-managed.
- Use Claude native deny permissions for narrowly defined sensitive paths that can be represented safely, and retain the `.agentsignore` hook for broader context-exclusion behavior and warnings.
- Preserve unrelated Claude settings, hooks, permission rules, and status-line choices through structural merges.
- Keep Codex project hooks and project configuration committed in `.codex`, while preserving unrelated user and project settings.
- Generate POSIX and Windows hook commands that resolve the repository root or installed helper path correctly when the session starts in a nested directory.
- Validate generated Claude JSON, Codex hook JSON, and Codex TOML before writing.
- Add integration fixtures for empty configuration, existing unrelated configuration, existing Shrinkydink-managed local configuration, nested working directories, and Windows command rendering.
- Report when a client requires trust review, restart, or another manual step before project hooks become active.

### Out of scope

- Modifying user-global Claude or Codex configuration.
- Supporting additional coding agents in this brief.
- Replacing client trust prompts, permissions, operating-system sandboxing, or secret-management systems.
- Guaranteeing enforcement for direct attachments, hosted tools, or client features that do not invoke project hooks.

## Acceptance criteria

- **AC-1** - A fresh clone containing the generated committed files has the Shrinkydink Claude `PreToolUse` guard available without first running Shrinkydink on that developer's machine or creating `.claude/settings.local.json`.
- **AC-2** - Existing personal `.claude/settings.local.json` content is not required for shared enforcement and is preserved byte-for-byte except for an explicit migration of a recognized Shrinkydink-managed entry.
- **AC-3** - Claude native deny permissions cover the generated high-confidence secret-path defaults, while `.agentsignore` negations and non-secret context exclusions continue to be evaluated by the hook rather than mistranslated into native permissions.
- **AC-4** - Codex and Claude hook commands locate their helper scripts when invoked from the repository root and from a nested subdirectory on POSIX systems.
- **AC-5** - Generated Windows commands use a tested repository-root or script-location resolution strategy and do not assume that the current working directory is the repository root.
- **AC-6** - Existing unrelated hooks and configuration survive apply and check cycles; a second apply is idempotent and generated JSON and TOML parse successfully.
- **AC-7** - An existing non-Shrinkydink status line is preserved, and the CLI reports the optional manual composition needed rather than replacing it.
- **AC-8** - The audit report distinguishes committed shared files, ignored local files, and client-specific activation or trust steps.

## Constraints and dependencies

- Follow the current public configuration schemas and precedence rules for Claude Code and Codex, and pin schema fixtures or source references used by tests.
- Never place secret values in generated configuration, hook output, tests, or documentation.
- Native deny permissions are defense in depth and must not be generated from patterns whose semantics cannot be represented faithfully.
- Cross-platform tests may use command-rendering and path-resolution fixtures where a real client executable is unavailable, but at least one documented manual smoke test should cover each supported client before release.
