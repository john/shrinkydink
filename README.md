# Shrinkydink

Shrinkydink configures a repository for smaller, safer coding-agent context. It creates a shared policy, a Git-ignore-style agent context file, and Claude Code and OpenAI Codex guardrails while preserving repository-owned configuration.

These guardrails are not a sandbox or a complete security boundary. Instructions and hooks can be bypassed by direct prompt attachments, unrecognized tool inputs, shell indirection, hosted tools, or clients that do not honor the configuration. Use filesystem permissions, secret management, and an external sandbox when you need hard isolation.

## Install

Copy this directory into one of the supported skill locations, then restart or reload the client:

```text
# Claude Code, repository or user scope
<repo>/.claude/skills/shrinkydink/
~/.claude/skills/shrinkydink/

# OpenAI Codex, repository or user scope
<repo>/.agents/skills/shrinkydink/
~/.agents/skills/shrinkydink/
```

Invoke it as `/shrinkydink` in Claude Code or `$shrinkydink` in Codex. You can also run the standard-library-only engine directly with Python 3.9+.

## Audit, apply, and check

Audit is read-only and is the default:

```bash
python3 scripts/shrinkydink.py --repo .
```

Review the planned changes, conflicts, warnings, recommendations, and any proposed `.gitattributes` normalization. Apply the complete validated change set transactionally:

```bash
python3 scripts/shrinkydink.py --repo . --apply
```

Verify that committed configuration matches the generated policy:

```bash
python3 scripts/shrinkydink.py --repo . --check --no-diff
```

`--check` exits `1` for drift or conflicts and `2` for invocation failure. Warnings and recommendations are non-mutating and do not fail a run by themselves. Use `--json` for CI; pin and review the script instead of fetching and executing it dynamically.

## What Shrinkydink manages

Shared configuration is intended to be committed. Local configuration remains personal and ignored.

| Path | Role | Treatment |
|---|---|---|
| `.shrinkydink.json` | Shared thresholds, mode, and configured agent-ignore path | Shared configuration |
| `.gitignore` | High-confidence and detected-ecosystem Git exclusions | Shared configuration |
| `.gitattributes` | Git line-ending normalization and binary diff behavior | Shared configuration |
| `.agentsignore` or configured path | Agent-context automatic defaults and user rules | Shared configuration |
| `AGENTS.md`, `CLAUDE.md` | Shared agent instructions and Claude import | Shared configuration |
| `.agent-tools/shrinkydink/*.py` | Standard-library runtime helpers | Shared configuration |
| `.claude/settings.json` | Claude hook, narrow native denials, and status line | Shared configuration |
| `.codex/hooks.json`, `.codex/config.toml` | Codex hooks and context footer | Shared configuration |
| `.claude/settings.local.json` | Optional personal Claude overrides | Local configuration; never created |

Text files are changed only inside `shrinkydink:start`/`shrinkydink:end` markers. In `.gitignore`, `.gitattributes`, and the configured agent-ignore file, Shrinkydink prepends its block, so later user rules and negations retain final precedence. Invalid formats, partial markers, unsafe symlinks, and paths resolving outside the repository become conflicts rather than replacements.

Apply preflights and stages every destination before writing. A replacement failure rolls back files already changed unless another process modified one after staging; independently changed files are left alone and reported. Shrinkydink never deletes, untracks, stashes, rewrites history, or rotates credentials.

## Automatic defaults and ecosystem detection

Automatic defaults are classified as `high-confidence` or `ecosystem-specific`, with a reason for every group. A repository with no detected ecosystem gets a deliberately narrow `.agentsignore` block:

- `.git/` and agent-local state;
- `.env` and `.env.*`, with example/sample/template negations;
- private-key and certificate extensions.

Ambiguous rules such as `vendor/`, `build/`, `out/`, databases, archives, source maps, Java packages, and generic binaries are not universal defaults. They can hide source or intentionally versioned fixtures.

Ecosystem-specific automatic defaults appear only when a marker is found. Reports identify every repository-relative marker that caused detection. Supported detections cover Node.js, Python, Rust, Go, Java/Gradle/Maven, .NET, Ruby, Terraform, and Swift. For example, `*.map` is Node-specific, `*.jar` and `*.war` are Java-specific, and Ruby uses `vendor/bundle/` rather than broad `vendor/`.

`.gitignore` and `.agentsignore` have different jobs, so their groups are not forced to be identical. `.gitignore` affects Git discovery; `.agentsignore` is a context-control convention.

## Diagnostics and JSON reports

Shrinkydink enumerates tracked filenames with Git and uses file metadata such as size. It does not open candidate files to classify diagnostics.

Tracked large, database, archive, generated, binary, or ambiguous-output paths become exact-path recommendations. Each recommendation includes the path, size when available, categories, reasons, configured agent-ignore path, and a root-anchored suggested rule. Recommendations are never applied automatically.

A tracked `.env`, `.env.*`, `.pem`, `.key`, `.p12`, or `.pfx` filename also produces a high-severity warning. `.gitignore` does not untrack a file or remove it from history. Follow your incident process to remove it as appropriate and rotate any exposed credential. Shrinkydink does not print, hash, sample, or inspect its contents and is not a comprehensive secret scanner.

JSON reports have `report_version: 1` and retain the original `repo`, `mode`, `ecosystems`, `settings`, `changes`, and `warnings` fields. Additive stable fields are:

- `ecosystem_detections` with marker evidence;
- `default_rule_groups` with classification, reason, target, rules, and detection markers;
- `conflicts`, projected from conflict entries that remain in `changes`;
- `recommendations` with non-mutating exact-path actions;
- `severity` on every warning.

Audit and check include `old` and `new` content for shared changed files while diffs are enabled. `--apply`, `--no-diff`, and local-configuration entries keep those keys as `null` to avoid exposing suppressed content.

## `.gitattributes` is Git policy

`.gitattributes` controls normalization, diff, and merge behavior; it does not control LLM access. When an established repository has user-owned attributes but no Shrinkydink block, audit emits a prominent warning because applying the proposed policy may renormalize files when they are later staged. `--apply` is the explicit approval boundary, and later user rules retain precedence.

## Agent-ignore policy and enforcement

The configured `agentsignore` path defaults to `.agentsignore`. Change it in `.shrinkydink.json`; generation, instructions, hooks, and checks use that one repository-relative path and leave a stale root file untouched.

Matching follows the documented Git-ignore subset: root anchoring, typed file/directory matches, `*`, `?`, bracket expressions, cross-directory `**`, ordered negation, escaped leading markers and spaces, normalized separators, and Git's excluded-parent rule. Run the packaged contract independently:

```bash
python3 scripts/shrinkydink.py --check-agentsignore-conformance
```

Policy modes are:

- `warn` (default): show the user a warning and add model-visible context, but allow the operation;
- `deny`: return lifecycle-hook denials for matched or conservatively broad operations;
- `off`: disable the runtime hook while retaining written instructions.

Use `deny` only as defense in depth. Known bypasses include Claude `@path` attachments, direct prompt uploads, unsupported tool schemas, arbitrary shell expansion and wrappers, hosted tools, and clients that ignore `AGENTS.md` or hooks. Native Claude denials intentionally cover only the exact `.env` name and private-key/certificate extensions because ordered arbitrary ignore rules cannot be translated safely.

See the [canonical matching contract](references/agentsignore.md) and [platform support and limits](references/platform-support.md) for exact behavior.

## Common scenarios

### New repository

Run audit, review the complete generated set, apply, commit the shared configuration, reload or trust client project settings, and run check. Claude users should confirm settings with `/status`; Codex users should inspect `/hooks`.

### Established repository

Audit first. Existing content outside managed blocks remains byte-preserved. Review the prominent `.gitattributes` warning and proposed diff before apply; no normalization is introduced without that explicit apply step. Keep repository-specific overrides after managed blocks.

### Intentionally versioned large fixture

The fixture appears as a recommendation, not an automatic exclusion. If agents need it, keep it versioned and take no action (or add a later negation if another rule excludes it). If they do not, copy the suggested exact rule into the user-owned portion of the configured agent-ignore file. Shrinkydink never broadens that suggestion to the whole extension or directory.

## Upgrade

There is no upgrade subcommand. After updating Shrinkydink:

1. Run `python3 scripts/shrinkydink.py --repo .`.
2. Review managed-block diffs, ecosystem evidence, warnings, and recommendations.
3. If upgrading from the former broad `.agentsignore` policy, add any intentionally retained broad rules outside the managed block.
4. Run `python3 scripts/shrinkydink.py --repo . --apply`.
5. Run `python3 scripts/shrinkydink.py --repo . --check --no-diff`.

The configuration schema remains version 1. Narrower defaults may reveal files that the old managed block hid; the upgrade warning makes that transition explicit and never copies old broad rules into user-owned space.

## Configuration and verification

CLI overrides include `--context-warning-percent 1-99`, `--ignore-mode warn|deny|off`, `--large-file-warning-kb KB`, `--no-claude`, `--no-codex`, `--json`, and `--no-diff`. Overrides persist through the shared `.shrinkydink.json` policy when applied.

Run the repository suite and dogfood check before release:

```bash
python3 -m unittest discover -s tests -t . -v
python3 scripts/shrinkydink.py --repo . --check --no-diff
```

Detailed references:

- [Configuration, generated files, transactions, and report fields](references/configuration.md)
- [Installation and invocation](references/installation.md)
- [Platform support, trust, hook coverage, and bypasses](references/platform-support.md)
- [Canonical `.agentsignore` semantics and conformance](references/agentsignore.md)

Questions and bug reports are welcome in GitHub Issues. Pull requests should include tests.
