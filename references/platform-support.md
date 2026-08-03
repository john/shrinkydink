# Platform support and limits

## Shared instruction architecture

`AGENTS.md` is the canonical shared instruction file. Codex reads it natively. Claude Code reads `CLAUDE.md`, so shrinkydink places `@AGENTS.md` in `CLAUDE.md` and keeps Claude-specific notes below the import. This avoids maintaining two divergent copies of the same rules.

## Claude Code

Shrinkydink configures committed `.claude/settings.json` with:

- `respectGitignore: true` when the setting is absent;
- an exec-form `PreToolUse` command hook rooted at `${CLAUDE_PROJECT_DIR}` for file-oriented tools and Bash;
- project-scoped `Read` and `Edit` denies for the exact `.env` filename and private-key/certificate extensions;
- a status-line command that reads `context_window.used_percentage` and warns at the configured threshold.

Arbitrary `.agentsignore` rules, `.env.*`, negations, dependency/cache rules, and user patterns are not translated into native denies because their ordering cannot be represented faithfully. The hook remains the full `.agentsignore` evaluator. Personal `.claude/settings.local.json` content is optional and is preserved byte-for-byte unless exact legacy Shrinkydink entries can be migrated safely.

An existing status line is preserved because Claude supports one status-line command per active setting layer and arbitrary composition is unsafe. In that case, the audit reports a manual integration warning. After committed project settings change, reload Claude settings and use `/status` to confirm their source and effective scope.

Claude PreToolUse does not run for files inserted directly with `@path`. A hard security boundary requires native permission-deny rules or an external sandbox; `.agentsignore` is not sufficient.

## OpenAI Codex

Shrinkydink configures project-local Codex hooks in `.codex/hooks.json`, unless the existing project config already uses inline hooks. It adds:

- `PreToolUse` for advisory or denying `.agentsignore` checks;
- `PreCompact` for a visible checkpoint/new-session warning.

It also ensures the TUI status line includes `context-remaining`. Codex currently exposes a native remaining-context footer and compaction lifecycle event, but not a project-hook field containing the exact context percentage. Therefore the configured numeric threshold is exact in Claude and advisory in Codex: Codex shows remaining context continuously and warns when compaction begins.

Project-local Codex hooks require the repository's `.codex` layer and hook definitions to be trusted. A changed hook may require review again; inspect it with `/hooks` after accepting the project or changed hook hash.

## Cross-agent ignore file

The configured `agentsignore` file (default `.agentsignore`) is a shrinkydink
convention, not a universal agent standard. It is honored through three layers:

1. written instructions in `AGENTS.md` and imported `CLAUDE.md`;
2. lifecycle hooks that inspect common path-bearing tool inputs;
3. narrow default patterns that exclude dependencies, caches, generated output, secrets, archives, and binary databases.

The guard can miss indirect shell expansion, tool-specific arguments it does not recognize, hosted tools, direct prompt attachments, and agent implementations that ignore both `AGENTS.md` and lifecycle hooks. Default to `warn`; use `deny` only as defense in depth, not as a substitute for filesystem permissions, secret management, or sandboxing.

The guard distinguishes proven-safe path-scoped searches from repository-wide scans. It inspects scalar, nested, and list-valued path fields for the configured file tools, `apply_patch` headers, and bounded operands for `cat`, `head`, `cp`, and `rm`. For search tools it keeps the content expression separate from filesystem targets: direct `Grep` and `Glob`, shell `rg`, recursive `grep`, `fd`, `find`, and recursive `ls` are treated as broad when they have no safe scope and an active ignore rule could be traversed.

Scope and exclusion proof is intentionally conservative. Anchored or path-qualified ignore rules can be proven disjoint from a narrow target, while an unanchored slashless rule such as `*.pem` can match below any directory. Recognized exact exclusions include negated `rg` globs, recursive `grep` `--exclude`/`--exclude-dir` values, and `fd` exclusions. Every active ignore rule must be covered before an otherwise broad operation proceeds silently. General glob containment, shell expansion, aliases, wrappers, and arbitrary program arguments remain outside the bounded parser.

The canonical matcher distinguishes files from directories, normalizes `/` and
`\` candidate separators plus dot components, resolves existing symlink
components, and rejects outside-repository candidates from repository-relative
evaluation. Drive and UNC spellings follow the host platform. Full syntax,
excluded-parent behavior, Docker Agent compatibility differences, and migration
notes are documented in [the `.agentsignore` contract](agentsignore.md).

In `warn` mode a finding returns both a user-visible `systemMessage` and model-visible `additionalContext`. In `deny` mode the same finding returns a current Claude/Codex `PreToolUse` denial. Messages can name paths and ignore rules but never read or include ignored-file contents.

## Runtime assumptions

The generated helpers require Python 3 and use only the standard library. The
matcher is installed beside `guard.py`, so direct execution does not depend on
the caller's `PYTHONPATH`. Python
3.11+ additionally enables parse validation of existing and generated Codex TOML
through `tomllib`. The guard discovers a root using `.git` or
`.shrinkydink.json`, so a configured ignore path also works in a non-Git
directory. POSIX Codex hook commands resolve the Git top level before invoking
helpers, while Claude uses its documented project-directory placeholder and
argument array. Native-Windows Codex overrides use PowerShell to resolve the Git
top level and join the installed helper path rather than depending on the
session working directory. Rendering and nested-path behavior are covered by
fixtures, but native client execution should still be smoke-tested because
PowerShell, Git, and Python-launcher availability varies. WSL or Git Bash
remains the most consistent fallback.

Before release, smoke-test Claude Code and Codex from the repository root and a
nested directory on POSIX, and from a nested directory on native Windows. Verify
Claude with `/status`, Codex with `/hooks`, and record any trust, reload, or
restart step required by the installed client version.

The regression suite budgets 50 representative in-process guard invocations at
no more than one second total on the supported Python 3.9+ test environment and
fails if the guard calls repository-walk APIs. This is a regression threshold,
not a real-time guarantee; each invocation reads only the policy file and the
configured ignore file rather than walking repository contents.
