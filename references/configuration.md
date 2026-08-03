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

- `warn`: show the user a warning and inject guidance into the agent context, but allow the tool call;
- `deny`: deny matched PreToolUse calls when the hook can identify a concrete ignored path;
- `off`: disable the runtime `.agentsignore` hook while retaining written instructions.

`large_file_warning_kb` controls the audit warning for tracked files. Shrinkydink does not automatically ignore or delete those files.

`agentsignore` may point to another repository-relative ignore file.

## Generated or managed files

| Path | Purpose | Expected version-control treatment |
|---|---|---|
| `.gitignore` | Stack-aware local, secret, cache, dependency, and build exclusions | Commit |
| `.gitattributes` | Text normalization and common binary declarations | Commit |
| `.agentsignore` | Agent-specific context exclusions | Commit |
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

For order-sensitive files—`.gitignore`, `.gitattributes`, and `.agentsignore`—the managed block is placed before existing repository content. Later user-maintained rules therefore retain final precedence, including negations and attribute overrides.

Before changing `.codex/config.toml`, shrinkydink validates existing TOML when the running Python includes `tomllib` (Python 3.11+). It also validates the generated result. On older Python versions, it emits a warning and preserves its conservative marker-based editing behavior.

Shrinkydink refuses to replace symbolic links. Newly created `.claude/settings.local.json` files use owner-only permissions where the filesystem supports POSIX modes; existing file modes are retained.

## `.agentsignore` syntax

The runtime helper implements the practical subset needed by the defaults:

- blank lines and `#` comments;
- `*`, `?`, character classes, and `**` wildcards;
- trailing `/` for directories;
- leading `/` for repository-root anchoring;
- `!` negation, with the last matching rule winning;
- patterns without `/` matching at any depth.

This is intentionally close to Git ignore behavior but is not a byte-for-byte implementation of every Git edge case. Keep custom rules straightforward and test them with representative hook payloads when using `deny` mode.

## Command-line interface

```text
--repo PATH                       repository or subdirectory
--apply                           write safe planned changes
--check                           report drift; exit 1 on drift/conflict
--context-warning-percent 1-99   override and persist threshold
--ignore-mode warn|deny|off       override and persist guard behavior
--large-file-warning-kb KB        override and persist large-file threshold
--no-claude                       omit Claude integration
--no-codex                        omit Codex integration
--json                            machine-readable report
--no-diff                         suppress audit/check unified diffs
```

Audit is the default and performs no writes.

## Suggested CI check

Install or vendor the skill script in a trusted tooling location, then run:

```bash
python3 path/to/shrinkydink/scripts/shrinkydink.py --repo . --check --no-diff
```

Do not fetch and execute the script dynamically in CI without pinning and reviewing the package.
