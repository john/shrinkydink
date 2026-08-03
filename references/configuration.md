# Shrinkydink configuration and generated files

## Configuration file

`.shrinkydink.json` is intended to be committed so collaborators use the same policy:

```json
{
  "version": 1,
  "context_warning_percent": 70,
  "ignore_mode": "warn",
  "large_file_warning_kb": 256,
  "agentsignore": ".agentsignore"
}
```

`context_warning_percent` is the used-context percentage at which Claude's generated status line changes from an informational reading to a warning. Valid values are 1-99.

`ignore_mode` supports:

- `warn`: show the user a warning and inject guidance into the agent context for a direct ignored-path match or a broad operation that may traverse ignored paths, but allow the tool call;
- `deny`: deny direct ignored-path matches and broad operations that may traverse ignored paths unless their recognized scope or explicit exclusions prove every active rule is avoided;
- `off`: disable the runtime `.agentsignore` hook while retaining written instructions.

`large_file_warning_kb` controls the audit warning for tracked files. Shrinkydink does not automatically ignore or delete those files.

`agentsignore` may point to another repository-relative ignore file. Planning,
generation, checks, runtime enforcement, and generated instruction prose all use
that configured path. A stale root `.agentsignore` is left untouched and is not
consulted when another path is configured.

## Generated or managed files

| Path | Purpose | Expected version-control treatment |
|---|---|---|
| `.gitignore` | Stack-aware local, secret, cache, dependency, and build exclusions | Commit |
| `.gitattributes` | Text normalization and common binary declarations | Commit |
| Configured `agentsignore` path (default `.agentsignore`) | Agent-specific context exclusions | Commit |
| `AGENTS.md` | Shared cross-agent context-hygiene instructions | Commit |
| `CLAUDE.md` | Imports `AGENTS.md` and adds Claude-specific notes | Commit |
| `.shrinkydink.json` | Shared policy and thresholds | Commit |
| `.agent-tools/shrinkydink/*.py` | Runtime guard and warning helpers | Commit |
| `.claude/settings.local.json` | Local Claude hooks and status line | Do not commit; shrinkydink adds it to `.gitignore` |
| `.codex/hooks.json` | Project Codex PreToolUse and PreCompact hooks | Commit |
| `.codex/config.toml` | Ensures Codex shows `context-remaining` | Commit |

If `.codex/config.toml` already contains inline hooks, shrinkydink adds its hooks there instead of creating a second hook representation.

## Managed blocks

Text files use one of these marker pairs:

```text
# shrinkydink:start
# shrinkydink:end
```

```text
<!-- shrinkydink:start -->
<!-- shrinkydink:end -->
```

Content outside the markers is preserved. A missing half of a marker pair is a conflict and is never repaired automatically.

For order-sensitive files—`.gitignore`, `.gitattributes`, and the configured
`agentsignore` path—the managed block is placed before existing repository
content. Later user-maintained rules therefore retain final precedence,
including negations and attribute overrides.

Before changing `.codex/config.toml`, shrinkydink validates existing TOML when the running Python includes `tomllib` (Python 3.11+). It also validates the generated result. On older Python versions, it emits a warning and preserves its conservative marker-based editing behavior.

Shrinkydink refuses to replace symbolic links and rejects a managed destination
when an existing parent component resolves outside the selected repository.
Apply performs a complete preflight and stages every new body before replacing
any destination. If preflight finds a conflict, nothing is written. If a
replacement fails, destinations already changed by that run are restored unless
one was independently changed after staging, in which case it is left alone and
reported. Newly created `.claude/settings.local.json` files use owner-only
permissions where the filesystem supports POSIX modes; existing file modes are
retained.

## `.agentsignore` syntax

See [the canonical `.agentsignore` contract](agentsignore.md) for supported
Git-ignore syntax, typed file/directory matching, excluded-parent negation,
normalization, Docker Agent compatibility, and migration guidance. In
particular, `build/` matches the directory and its descendants but not a regular
file named `build`.

## Command-line interface

```text
--repo PATH                       repository or subdirectory
--apply                           write the full validated change set transactionally
--check                           report drift; exit 1 on drift/conflict
--check-agentsignore-conformance run packaged matching fixtures; exit 0/1/2
--context-warning-percent 1-99   override and persist threshold
--ignore-mode warn|deny|off       override and persist guard behavior
--large-file-warning-kb KB        override and persist large-file threshold
--no-claude                       omit Claude integration
--no-codex                        omit Codex integration
--json                            machine-readable report
--no-diff                         suppress audit/check unified diffs
```

Audit is the default. Audit and check perform no filesystem writes, including
temporary-file creation in the target repository.

JSON audit and check reports include `old` and `new` content for create and
update entries when diffs are enabled. `--apply` and `--no-diff` reports retain
those keys with `null` values so write operations and explicitly suppressed
diffs do not expose file content.

## Suggested CI check

Install or vendor the skill script in a trusted tooling location, then run:

```bash
python3 path/to/shrinkydink/scripts/shrinkydink.py --repo . --check --no-diff
```

Do not fetch and execute the script dynamically in CI without pinning and reviewing the package.

To validate the packaged matching contract independently of a target repository:

```bash
python3 path/to/shrinkydink/scripts/shrinkydink.py --check-agentsignore-conformance
```
