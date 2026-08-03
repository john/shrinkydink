# Plan: Safe transactional repository writes

Source brief: docs/features/0001-safe-transactional-repository-writes.md
Status: implemented
Planned against commit: 7d4027c0e285e2007812f7a9853382ebd186f41e
Base commit: 7d4027c0e285e2007812f7a9853382ebd186f41e

## Outcome

Shrinkydink cannot write outside the repository it was pointed at, and `--apply` either completes the entire validated change set or leaves the repository as it was. The `agentsignore` value from `.shrinkydink.json` is honored consistently by planning, generation, checking, runtime enforcement, and the generated instruction prose.

## Scope

### In scope

- Resolve the repository root once and validate every managed destination against it before any write.
- Reject a destination when the file or any existing parent component is a symlink resolving outside the repository.
- Use the effective `agentsignore` value everywhere instead of hard-coding `.agentsignore` during generation, including in generated instruction prose.
- Full preflight before writing: any conflict, invalid configuration, unsafe path, or unreadable target prevents all writes.
- Stage every new file body before replacing any destination; restore every changed destination if a replacement fails mid-run.
- Preserve existing file modes; keep owner-only mode for new Claude local settings and executable mode for runtime helpers.
- Regression tests for custom ignore paths, unsafe symlinked parents, invalid configuration, partial-write failure, permission preservation, and idempotence.

### Out of scope

- A security sandbox for the coding agent after repository setup.
- Crash consistency across power loss or forced process termination.
- Modifying Git history, removing tracked files, committing, or operating on multiple repositories per invocation.
- Removing or migrating an existing `.agentsignore` when the config points elsewhere; the stale file is left untouched.

## Assumptions and decisions

Confirmed with the user during planning:

- **D-1 — `--apply` is strictly all-or-nothing.** No opt-out flag is added. Today's documented behavior ("write safe planned changes", writing valid destinations and skipping conflicted ones) becomes abort-on-any-conflict. This is a deliberate breaking change, limited to runs that already exited 1.
- **D-2 — Generated prose names the configured ignore path.** When `agentsignore` is `config/agent-ignore`, generated `AGENTS.md`, `CLAUDE.md`, and ignore-file header text refer to `config/agent-ignore`. Otherwise the instructions would tell agents to honor a file that does not exist.

Assumptions made without asking:

- **D-3 — Tests use stdlib `unittest`, with no `pyproject.toml`, `tox.ini`, or other packaging marker.** The brief prefers a standard-library implementation; pytest is not installed and the host runs Python 3.9.6. This choice is also load-bearing: `detect_ecosystems` keys on `pyproject.toml`/`requirements.txt`/`setup.py`/`tox.ini`, so adding one would flip this repo's own detection from `none` to `python`, churn its generated `.gitignore` block, and break the AC-7 idempotence check against this repository. Tests must stay Python 3.9 compatible.
- **D-4 — Failure injection for AC-5 uses `unittest.mock.patch` on `os.replace`.** No test-only hook is added to production code.
- **D-5 — Rollback compares against what Shrinkydink wrote,** not against the plan-time snapshot. A destination whose current bytes no longer match what this run wrote is reported and left alone rather than overwritten, per the brief's rollback constraint.
- **D-6 — Backups are captured at stage time,** not from the plan-time `Change.old`, closing the window between planning and applying.
- **D-7 — Executable mode becomes an explicit field on `Change`,** replacing the current `content.startswith("#!/usr/bin/env python3")` sniff in `atomic_write`. Same observable behavior, no content heuristic.
- **D-8 — `guard.py` root discovery also probes `.shrinkydink.json`.** It currently probes `.git` or a literal `.agentsignore`; with a custom ignore path in a non-Git directory, discovery would degrade.
- **D-9 — Invalid configuration falls back to the default `.agentsignore`** for path resolution, matching the existing `desired_config({}, args)` fallback. Under D-1 an invalid config is a conflict and blocks all writes anyway.

Implementation deviations recorded by `run`:

- **D-10 — Added `tests/__init__.py`.** Python 3.9 requires the discovery directory to be importable when the approved `python3 -m unittest discover -s tests -t . -v` command uses `-t .`. The empty package marker is the minimum change that makes the recorded verification command execute.
- **D-11 — Added final preflight concurrency coverage.** `apply_changes` now rejects destinations that appear, disappear, or change after planning but before staging. Two focused tests also cover removal of transaction-created directories and the D-5 independent-change rollback safeguard. This tightens the approved transaction boundary without changing feature scope.

## Confirmed current behavior

Reproduced read-only at the planning commit, in throwaway repositories:

- **AC-2 fails.** With `"agentsignore": "config/agent-ignore"`, `--apply` creates root `.agentsignore` and never creates `config/agent-ignore`. `build_plan` hard-codes `root / ".agentsignore"` ([scripts/shrinkydink.py:865](../../scripts/shrinkydink.py#L865)) although `effective["agentsignore"]` is already computed and validated.
- **AC-3 fails, and it is a live escape.** With `.claude` symlinked to a directory outside the repository, `--apply` wrote `settings.local.json` outside the repository and **exited 0** with no conflict reported. `classify_change` checks only the destination itself for symlinks ([scripts/shrinkydink.py:161](../../scripts/shrinkydink.py#L161)); no parent component or containment check exists.
- **AC-4 fails.** With `AGENTS.md` holding an unterminated managed block, `--apply` exited 1 but still wrote `.gitignore`, `.gitattributes`, `.agentsignore`, `.shrinkydink.json`, and `.codex/hooks.json`. `main` calls `apply_changes` unconditionally ([scripts/shrinkydink.py:1073](../../scripts/shrinkydink.py#L1073)).
- **AC-5 has no implementation.** `apply_changes` marks a failed write as a conflict and continues to the next destination ([scripts/shrinkydink.py:962-974](../../scripts/shrinkydink.py#L962-L974)).
- **AC-1 and AC-7 appear satisfied but are untested.** `build_plan` performs no writes, and `--check --no-diff` against this repository exits 0.
- **AC-6 is implemented and untested.** Mode preservation lives in `atomic_write` ([scripts/shrinkydink.py:806-826](../../scripts/shrinkydink.py#L806-L826)).

## Acceptance-criteria traceability

| ID | Acceptance criterion | Implementation | Verification | Status |
|---|---|---|---|---|
| AC-1 | Audit and check modes perform no filesystem writes, including temporary files | Read-only planning remains in `build_plan` (`scripts/shrinkydink.py:884`); staging is reachable only from apply | `test_audit_and_check_do_not_touch_filesystem` (`tests/test_shrinkydink.py:61`); final unittest suite passed | pass |
| AC-2 | Custom `agentsignore` path is created, checked, and read by the runtime guard; no second root `.agentsignore` | Effective path threaded through `agentsignore_body`, `agents_md_body`, `claude_md_body`, and `build_plan` (`scripts/shrinkydink.py:457`, `:542`, `:556`, `:884`); guard discovers `.shrinkydink.json` and reports the configured path | `test_custom_agentsignore_path_is_used` (`tests/test_shrinkydink.py:77`) proves creation, prose, guard matching, and that a stale root file is not consulted; final suite passed | pass |
| AC-3 | A parent symlink resolving outside the repository is a conflict; nothing is created or changed outside | `resolve_managed_destination` validates containment before any destination read or write (`scripts/shrinkydink.py:114`) | `test_symlinked_parent_outside_repo_is_conflict` (`tests/test_shrinkydink.py:125`); final suite passed | pass |
| AC-4 | Any conflicted or invalid change means no otherwise-valid destination is written | `main` gates apply before `apply_changes`; apply performs a second complete no-write preflight (`scripts/shrinkydink.py:1091`, `:1355`) | `test_conflict_blocks_all_writes`, `test_invalid_config_blocks_all_writes`, and `test_apply_preflight_detects_change_after_planning`; final suite passed | pass |
| AC-5 | Simulated replacement failure restores all changed destinations, exits nonzero, reports failure and restoration | `apply_changes` stages all bodies, commits with `os.replace`, compares written hashes, rolls back in reverse, and removes empty transaction-created directories (`scripts/shrinkydink.py:1091`) | `test_replacement_failure_rolls_back`, `test_replacement_failure_removes_new_files_and_directories`, and `test_rollback_does_not_overwrite_independent_change`; final suite passed | pass |
| AC-6 | Existing modes retained; new Claude local settings owner-only; runtime helpers executable | `Change.mode` carries explicit new-file modes; staging and rollback preserve prior POSIX modes (`scripts/shrinkydink.py:44`, `:1091`) | `test_permissions_preserved_and_assigned` (`tests/test_shrinkydink.py:260`); final suite passed on POSIX | pass |
| AC-7 | After a successful apply, an immediate `--check --no-diff` reports no drift and exits 0 | Transaction output and configured-path generation are idempotent | `test_apply_then_check_is_clean` (`tests/test_shrinkydink.py:277`) passed for default and custom paths; repository self-check exited 0 with all rows `OK` | pass |

## Verification

| Command | Purpose | Baseline result | Final result |
|---|---|---|---|
| `python3 -m unittest discover -s tests -t . -v` | New regression suite covering AC-1 through AC-7 | exit 1: `ImportError: Start directory is not importable: 'tests'` (suite did not exist) | exit 0: 11 tests passed | improved; new suite passes |
| `python3 scripts/shrinkydink.py --repo . --check --no-diff` | This repository stays self-consistent; guards AC-7 against real content | exit 0, all rows `OK`; expected Python 3.11+ Codex TOML validation warning | exit 0, all rows `OK`; same expected warning | unchanged/pass |
| `python3 -m compileall -q scripts assets/runtime` | Both edited scripts stay syntactically valid on the host interpreter | exit 0 | exit 0 | unchanged/pass |
| `python3 scripts/shrinkydink.py --repo . --apply` | Regenerate the installed guard through the product path | not applicable | exit 0; only `.agent-tools/shrinkydink/guard.py` updated, all other destinations `OK` | pass |
| `git diff --check` | Detect whitespace errors in the implementation diff | not applicable | exit 0 | pass |
| `cmp -s assets/runtime/guard.py .agent-tools/shrinkydink/guard.py` | Confirm generated runtime copy matches its source asset | not applicable | exit 0 | pass |

The repository has no external test framework, CI, or packaging config. The suite uses stdlib `unittest`. Host interpreter is Python 3.9.6, so no `tomllib` is available and the Codex TOML-validation warning is expected in output. Bytecode caches created by verification were removed before commit. No graphical interface changed, so screenshot-based visual verification was not applicable; CLI reports were exercised directly by the tests and repository self-check.

## Implementation steps

1. **Containment primitive.** Add `resolve_managed_destination(root, relative) -> tuple[Optional[Path], Optional[str]]` to `scripts/shrinkydink.py`. Reject absolute paths and `..` components; walk from `root` down each existing component and, for any symlink encountered, verify its real path stays within `realpath(root)`; verify the deepest existing ancestor is contained. Return a conflict reason string instead of raising.
2. **Route every managed path through it.** In `build_plan`, resolve each destination — text targets, runtime helpers, Claude settings, Codex config and hooks, `.shrinkydink.json` — and emit `conflict(...)` when the check fails, so unsafe paths surface in audit and check output too, never only at write time.
3. **Honor the effective ignore path (AC-2).** Replace the hard-coded `root / ".agentsignore"` with `root / effective["agentsignore"]`. Thread the ignore name into `agentsignore_body`, `agents_md_body`, and `claude_md_body` per D-2. Keep the `.agentsignore` default so unconfigured repositories see byte-identical output.
4. **Guard root discovery (D-8).** In `assets/runtime/guard.py`, add `.shrinkydink.json` to the root-marker probe in `repo_root`. Regenerate `.agent-tools/shrinkydink/guard.py` via the script's own apply, not by hand-editing.
5. **Preflight gate (AC-4).** In `main`, when `args.apply` and any change is a conflict, skip `apply_changes` entirely, report which conflicts blocked the run, and return 1 without writing.
6. **Stage/commit/rollback (AC-5).** Replace `atomic_write` and `apply_changes` with a two-phase implementation: stage each changed destination to a sibling temp file with its final mode; then `os.replace` each into place, recording prior bytes, prior mode, prior existence, and a hash of what was written. On any commit-phase failure, roll back in reverse: skip and report destinations whose current bytes no longer match what this run wrote (D-5), otherwise restore prior bytes and mode or delete files that did not exist before. Remove directories this run created, only when empty. Clean up staged temp files on every exit path. Return a structured result the reporter can print.
7. **Explicit executable mode (D-7).** Add a mode hint to `Change`, set it for runtime helpers and Claude settings at plan time, and drop the shebang sniff.
8. **Tests.** Add `tests/test_shrinkydink.py`, loading the script with `importlib.util.spec_from_file_location`. Provide a helper that builds a throwaway Git repository in a `TemporaryDirectory`. Cover every row in the traceability table. Gate symlink cases on `os.symlink` availability and mode cases on POSIX support, skipping with an explicit reason as the brief requires.
9. **Documentation.** Update `references/configuration.md`: the `--apply` line under "Command-line interface" and the "Audit is the default" note, the symlink sentence under "Managed blocks" to cover parent components and containment, and the `agentsignore` note to state that prose follows the configured path. Update `references/platform-support.md` if the guard-discovery change alters its description. Check `SKILL.md` step 3 and `references/installation.md:55` for wording that implies partial application.
10. **Verify.** Run all three commands, apply the script to this repository, confirm `--check --no-diff` still exits 0, and remove `__pycache__` before committing.

## Files likely to change

- `scripts/shrinkydink.py` — containment, effective ignore path, preflight, stage/commit/rollback, `Change` mode field
- `assets/runtime/guard.py` — root-marker probe
- `.agent-tools/shrinkydink/guard.py` — regenerated, not hand-edited
- `tests/test_shrinkydink.py` — new
- `references/configuration.md` — `--apply` semantics, symlink/containment wording, `agentsignore` prose
- `references/platform-support.md`, `SKILL.md`, `references/installation.md` — only if wording implies partial application

## Risks and follow-ups

- **Breaking change (D-1).** `--apply` no longer writes anything when any destination conflicts. Previously users could apply the valid subset and fix conflicts afterward. Call this out in the pull-request description.
- **Prose change (D-2) is invisible at the default setting** but rewrites `AGENTS.md` and `CLAUDE.md` for repositories using a custom path; their next `--check` will report drift once. Expected, and worth noting in the pull request.
- **Rollback is not crash-consistent,** explicitly out of scope. A kill between two `os.replace` calls leaves a partially applied tree; the next `--check` reports the drift.
- **`os.replace` is atomic only within a filesystem.** Staging as a sibling of each destination preserves that; a destination whose parent is a mount point or bind mount still behaves correctly because the temp file lives in the same directory.
- **Windows** cannot represent the symlink and POSIX-mode cases; those tests skip with an explicit reason, so coverage there is weaker. Consistent with the brief's constraint.
- **`repo_root` in `guard.py` is duplicated logic** from `resolve_repo` in the main script with different rules. Unifying them is a plausible follow-up but is not required here and would widen scope.
- **Follow-up:** this repository has no CI. `references/configuration.md` already suggests a `--check` command; wiring the new unittest suite plus that check into CI would keep the guarantees from regressing.
