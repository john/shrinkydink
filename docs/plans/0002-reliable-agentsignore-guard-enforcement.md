# Plan: Reliable `.agentsignore` guard enforcement

Source brief: docs/features/0002-reliable-agentsignore-guard-enforcement.md
Status: implemented
Planned against commit: a4a3aa2403c214c920dd54ca7981732d6adf233c
Base commit: 10aec619153de9858bdce789f667be893c90bedc

## Outcome

Shrinkydink's generated `PreToolUse` guard reliably recognizes ignored paths in the bounded Claude and Codex tool shapes it claims to support. It handles scalar, nested, list-valued, bare-filename, glob, subdirectory, and `apply_patch` path inputs; distinguishes search expressions from search targets; and treats unscoped repository traversal as risky. `warn` mode remains advisory and supplies both user- and model-visible context, while `deny` mode emits a contract-valid blocking response for direct matches and broad operations that are not proven safe.

## Scope

### In scope

- Extract candidate paths from scalar path fields, nested objects, and list-valued `paths`/`files`-style fields without scanning content, prompts, queries, or replacement text.
- Parse a bounded set of shell command operands so bare filenames used by `cat`, `head`, `cp`, and `rm` are treated as paths, while preserving existing absolute, relative, glob, subdirectory, and `apply_patch` handling.
- Keep search-pattern parsing separate from path-target parsing for direct `Grep`/`Glob` calls and shell `rg`, recursive `grep`, `fd`, `find`, and recursive `ls` operations.
- Classify unscoped repository searches/listings as broad whenever at least one effective ignore rule remains, unless recognized scope/exclusion arguments conservatively prove the operation cannot traverse any ignored path.
- Emit concise warnings or denials that name matched paths/rules (or the relevant active rules for a broad operation), recommend a narrower operation, and never read ignored-file contents.
- Validate representative Claude and Codex inputs and every emitted response shape against retained, sanitized contract fixtures derived from current public documentation.
- Add table-driven behavior, contract, and performance coverage using only the Python standard library.
- Update the guard-behavior documentation without changing `.agentsignore` pattern semantics or presenting the hook as a sandbox.

### Out of scope

- Fully parsing arbitrary shell programs, aliases, functions, `eval`, command substitution, dynamic variable expansion, or applications that open files internally.
- Blocking hosted tools, language servers, prompt attachments, Claude `@` imports, explicit file imports, or agent implementations that do not execute the configured hook.
- Changing the pattern language implemented by `parse_rules`, beyond using the existing parsed rules to reason about operation scope; pattern-semantics work remains deferred to brief 0003.
- Adding a third-party schema validator, a new packaging configuration, a sandbox, or a complete secret-protection boundary.
- Broadening the configured hook matchers or adding support for unrelated tools beyond the existing Claude/Codex `Read`, `Glob`, `Grep`, `Edit`, `Write`, `Bash`, and Codex `apply_patch` surface.

## Assumptions and decisions

No blocking questions were required; the brief and existing repository conventions determine the externally visible behavior. The following implementation decisions make the bounded interpretation explicit:

- **D-1 — The existing hook matchers define supported tools.** Claude covers `Read`, `Glob`, `Grep`, `Edit`, `Write`, and `Bash`; Codex covers those names plus `apply_patch`. Generic nested/list path extraction is reusable within those payloads, but this feature does not silently widen hook configuration to every local or MCP tool.
- **D-2 — Safety proof is conservative and reversible.** A direct file path is safe when it does not match an effective rule. A directory/search scope is safe only when rule-prefix analysis proves no effective rule can match at or below that scope. Slashless rules such as `*.pem` can match below any directory, so a directory scope alone cannot prove safety for them. An unscoped broad operation is exempted only when recognized exclusion arguments cover every effective rule; uncertain coverage remains broad.
- **D-3 — Explicit exclusions use bounded normalization.** Recognize the exclusion forms already meaningful to the supported search commands (for example `rg -g '!pattern'`, recursive `grep --exclude/--exclude-dir`, and `fd -E/--exclude`). Normalize leading `./`, trailing directory slashes, and the directory `/**` form. Exact equivalent patterns count as proof; do not attempt general glob-set algebra.
- **D-4 — `assets/runtime/guard.py` is the source of truth.** `scripts/shrinkydink.py::runtime_asset` installs it. After changing the asset, run Shrinkydink's apply path to regenerate `.agent-tools/shrinkydink/guard.py`, and verify the two copies are byte-identical. Do not maintain divergent hand-edited implementations.
- **D-5 — Use the cross-platform output intersection.** Current Claude and Codex `PreToolUse` contracts both accept top-level `systemMessage` and `hookSpecificOutput` containing `hookEventName: "PreToolUse"`, `additionalContext`, and, for denial, `permissionDecision: "deny"` plus `permissionDecisionReason`. Warn output uses no permission decision; deny output always includes the blocking fields. Contract evidence was reviewed on 2026-08-03 from the Claude Code hooks reference, the current Codex manual, and Codex's generated `pre-tool-use.command.{input,output}.schema.json` files. Retained fixture documentation must name those sources and the review date.
- **D-6 — Contract tests are strict even though runtime parsing is tolerant.** The guard may continue to fail open on malformed hook input, but test helpers must reject malformed JSON, unknown emitted keys, a wrong event name, missing/non-string messages, or a denial lacking both `permissionDecision` and `permissionDecisionReason`. Negative tests prove malformed output is caught rather than accidentally treated as an advisory warning.
- **D-7 — Performance threshold.** A guard-focused test will execute 50 representative in-process invocations in at most 1.0 second total on the supported Python 3.9+ test environment, excluding one-time module import. A companion assertion patches repository-walk APIs such as `Path.rglob` and `os.walk` to fail if called. Document this threshold as a regression budget, not a real-time guarantee.
- **D-8 — Keep tests on stdlib `unittest` and Python 3.9.** The repository has no external test framework or packaging configuration, and the current interpreter is Python 3.9.6. Fixtures are JSON/Markdown files; response validation is a small purpose-built test helper rather than a dependency on `jsonschema`.
- **D-9 — Preserve unrelated work.** Planning occurred on `feat/0001-safe-transactional-repository-writes` at `a4a3aa2`; `origin/main` points to `10aec61`. The working tree already contains untracked `.agents/`, `.claude/`, and the 0002 brief. No existing 0002 branch, plan, or pull request was found. `run` must preserve all user-owned paths, establish its base per the feature git workflow, and record the actual base commit without cleaning, stashing, or overwriting this work.

Implementation deviations recorded by `run`: none. The implementation followed D-1 through D-9. The `apply_patch` parser additionally accepts the current `*** Move to:` header while retaining the pre-existing `*** Move to File:` form; this is the planned continuation of apply-patch header coverage, not expanded feature scope.

## Planning-time implementation findings

- `assets/runtime/guard.py::strings_from_paths` yields scalar strings only when they are direct values of singular `PATH_KEYS`; recursive list traversal drops string members, and plural path-bearing keys are absent.
- `shell_path_candidates` only recognizes shell tokens containing `/`, `\`, or a leading `.`, so the brief's bare `private.pem`/`output.bin` operands bypass direct matching.
- Search-specific parsing already separates the first `rg` positional from later target paths and detects unscoped `rg`, recursive `grep`, `fd`, `find`, and `ls -R` calls, providing a useful base to preserve.
- `main` computes `broad_search`, but deny output is currently added only when `matches` is non-empty. A broad operation with no concrete match therefore emits advisory context even in `deny` mode, which does not satisfy AC-4.
- Direct-match messages identify rules, while the broad-search message names only the ignore file. It needs bounded rule details and explicit narrowing/exclusion guidance for AC-4 and AC-5.
- The current output shape is in the documented Claude/Codex intersection, but the repository has no strict hook-contract fixtures or guard-focused response tests. The only existing guard exercise is the custom-ignore-path integration case in `tests/test_shrinkydink.py`.
- Guard logic reads only the config and configured ignore file and performs no repository walk. The implementation must retain that property and make it test-visible.

## Acceptance-criteria traceability

| ID | Acceptance criterion | Implementation | Verification | Status |
|---|---|---|---|---|
| AC-1 | In both Claude-style and Codex-style fixtures, direct tool inputs containing a matching path are detected whether the path is a scalar, nested value, or member of a list such as `paths` or `files`. | `PATH_KEYS` and key-sensitive `strings_from_paths` in `assets/runtime/guard.py`; sanitized fixtures in `tests/fixtures/hooks/` | `test_scalar_nested_and_list_paths_for_both_platforms` and `test_every_supported_tool_has_a_matching_fixture`; full suite exit 0 | pass |
| AC-2 | Shell commands including `cat private.pem`, `head private.pem`, `cp private.pem copy.pem`, and `rm build/output.bin` identify their relevant path operands even when an operand contains no slash. | `analyze_shell_command`, `positional_args`, and `option_values` in `assets/runtime/guard.py` | `test_bare_shell_operands_are_paths` covers all required commands plus source/destination variants; full suite exit 0 | pass |
| AC-3 | Search expressions such as `rg private.pem src/` do not treat `private.pem` as a path merely because it resembles a filename; the explicitly scoped `src/` target determines whether the operation is broad. | Search-specific branches in `analyze_shell_command` and `direct_search_operation` keep patterns separate from scopes | `test_search_expression_is_not_treated_as_a_path` covers shell `rg` and direct `Grep`, scoped and unscoped; full suite exit 0 | pass |
| AC-4 | In `deny` mode, an unscoped repository-wide search or recursive listing is blocked when the active ignore file contains at least one effective exclusion. The response explains that the operation must be narrowed or explicitly exclude ignored paths. | `effective_ignore_rules`, `operation_may_traverse_ignored`, `rule_may_match_under`, and deny response construction | `test_broad_operations_block_in_deny_mode` covers direct `Grep`/`Glob`, `rg`, recursive `grep`, `fd`, `find`, and `ls -R`; `test_complete_explicit_exclusions_prove_broad_search_safe`; full suite exit 0 | pass |
| AC-5 | In `warn` mode, the same broad operation proceeds but supplies a warning to the user and model without exposing contents from an ignored file. | Broad finding message populates top-level `systemMessage` and hook-specific `additionalContext` without candidate reads | `test_warn_mode_supplies_context_without_reading_ignored_content` verifies both channels and sentinel absence; full suite exit 0 | pass |
| AC-6 | A direct nonmatching path and a narrowly scoped operation outside ignored paths proceed without a warning or denial. | Direct matching plus conservative scope/exclusion proof returns no output for proven-safe operations | `test_nonmatching_and_proven_safe_scopes_are_silent`, `test_absolute_relative_and_subdirectory_paths`, `test_content_fields_are_not_treated_as_paths`, and complete-exclusion cases; full suite exit 0 | pass |
| AC-7 | Denials produced by the guard are recognized as blocking decisions by current Claude and Codex hook-output fixtures; malformed output fails tests rather than silently degrading to a warning. | Cross-platform response intersection in `main`; strict `validate_claude_output`/`validate_codex_output`; fixture provenance README | Every warning/denial helper validates both contracts; `test_contract_validators_reject_malformed_output` proves malformed shapes fail; full suite exit 0 | pass |
| AC-8 | Guard execution remains fast enough for interactive use, with a documented test threshold and no repository-wide filesystem walk on each hook invocation. | Guard reads only config/ignore inputs; threshold and bounded support documented in `references/platform-support.md` | `test_guard_performance_budget_and_no_repository_walk` completes 50 calls within 1.0s and makes `Path.rglob`/`os.walk` fatal; focused suite completed all 15 tests in 0.038s | pass |

## Verification

Per the `feat plan` workflow, no baseline was executed during planning; `run` records the baseline and final results.

| Command | Purpose | Baseline result | Final result |
|---|---|---|---|
| `python3 -m unittest tests.test_guard -v` | Focused guard behavior, contracts, message safety, and performance | unavailable; test module did not exist at base commit | exit 0; 15 tests passed in 0.038s |
| `python3 -m unittest discover -s tests -t . -v` | Existing and new table-driven behavior, platform contracts, message safety, and D-7 performance budget | exit 0; 12 tests passed in 0.346s | exit 0; 27 tests passed in 0.382s |
| `python3 scripts/shrinkydink.py --repo . --apply` | Regenerate the installed guard through the product's transactional apply path | not applicable; implementation step | exit 0; only `.agent-tools/shrinkydink/guard.py` updated; all other destinations `OK`; expected Python 3.11+ warning |
| `python3 scripts/shrinkydink.py --repo . --check --no-diff` | Repository self-consistency after regenerating the installed guard and updating managed documentation | exit 0; all destinations `OK`; expected Python 3.11+ Codex TOML-validation warning on Python 3.9.6 | exit 0; all destinations `OK`; same expected warning |
| `cmp -s assets/runtime/guard.py .agent-tools/shrinkydink/guard.py` | Prove the committed dogfood runtime is byte-identical to its source asset | exit 0; copies identical | exit 0; copies identical |
| `git diff --check` | Reject whitespace errors in source, fixtures, tests, and documentation | exit 0 | exit 0 |

## Implementation steps

1. **Add fixture and harness foundations.** Create sanitized Claude and Codex `PreToolUse` base payloads under `tests/fixtures/hooks/`, plus a short fixture README naming the official source URLs and 2026-08-03 review date. Add `tests/test_guard.py` with helpers that load `assets/runtime/guard.py`, override root resolution to a temporary repository, invoke `main` with isolated stdin/stdout, and parse empty or JSON output deterministically.
2. **Make path extraction key-sensitive and list-aware.** Replace the current recursion with an extractor that tracks whether it is inside a known path-bearing field. Accept strings, nested dictionaries, and arbitrarily nested lists/tuples only in that context; add explicit plural forms (`files`, `paths`, `file_paths`, `directories`, `roots`, `targets`, `sources`, `destinations`). Continue skipping content/query/prompt/replacement fields. Deduplicate after normalization as today.
3. **Introduce bounded shell operand specifications.** Reuse `shell_segments` and `positional_args`, strip leading environment assignments, and dispatch by executable. For `cat`, `head`, `cp`, and `rm`, extract the relevant positional operands even when bare, honoring `--` and options that consume a value; for `cp`, inspect both sources and destination. Preserve `PATCH_PATH_RE` and existing slash/glob extraction for unsupported commands without claiming full shell parsing.
4. **Separate search expressions, scopes, and exclusions.** Refactor the current broad-search code so `rg`/recursive `grep`/`fd` patterns never become candidate paths, while explicit targets do. Keep `find` roots and recursive `ls` targets distinct. Apply the same distinction to direct `Grep` (`pattern` is content; `path` is scope; `glob` is a file filter) and `Glob` (`pattern` plus optional `path` define filesystem scope).
5. **Evaluate effective rules and scope overlap.** Add small helpers that identify live non-negated rules (including exact later-negation cancellation), compare direct file candidates with `match_rule`, and conservatively determine whether a rule may match at or below a directory/glob scope using anchoring, slashless-pattern, and literal-prefix information already available on `Rule`. A proven-disjoint scope is narrow/safe; uncertainty remains broad.
6. **Recognize complete exclusions conservatively.** Parse only the documented exclusion flags for supported search commands. Normalize patterns per D-3 and treat a broad operation as safe only if every effective rule has an exact-equivalent exclusion. Add positive tests for exact coverage and negative tests for partial or ambiguous coverage. Do not change `translate_gitignore` or claim arbitrary glob containment.
7. **Unify findings and response construction.** Represent concrete matches and unsafe broad traversal as explicit findings. Build concise messages from the finding: list at most four paths/rules (or active rules for broad traversal), summarize any remainder, recommend a narrow target or complete explicit exclusions, and keep the existing warn/deny policy guidance. Never stat or read a candidate path.
8. **Make deny mode actually block broad operations.** In `main`, emit `permissionDecision: "deny"` and `permissionDecisionReason` whenever mode is `deny` and either finding type exists. In warn mode, emit `systemMessage` plus hook-specific `additionalContext` and no decision. Return no output for AC-6 cases and keep `off`/invalid-input behavior unchanged.
9. **Add exhaustive table-driven tests.** Cover each supported tool name and representative Claude/Codex shape; scalar/nested/list paths; absolute/relative/bare/glob paths; `cwd` in a repository subdirectory; all `apply_patch` headers; command operands; pattern-versus-target handling; direct and broad warn/deny; complete/partial exclusions; no-rule/off cases; match truncation; and a sentinel ignored file whose contents must never appear.
10. **Enforce response contracts in tests.** Implement strict stdlib validators for the emitted common subset, including allowed-key/type checks, exact event name, context-channel requirements, and blocking-decision requirements. Run every warn and deny response through both the Claude and Codex validators, and add malformed samples that demonstrate the validators fail closed.
11. **Add and document the performance guardrail.** Test D-7 with temporary config/ignore files and representative payloads, failing on repository-walk APIs. Update `references/platform-support.md` with supported bounded command/search behavior, broad-operation semantics, caveats, and the threshold. Update `references/configuration.md` so `warn` and `deny` accurately describe direct matches and broad traversal.
12. **Regenerate and verify.** Run `python3 scripts/shrinkydink.py --repo . --apply` as an implementation step to refresh `.agent-tools/shrinkydink/guard.py` from the asset. Then execute every verification command above, record baseline/final outcomes in this plan, and keep unrelated working-tree content untouched.

## Files likely to change

- `assets/runtime/guard.py` — canonical extraction, shell/search parsing, scope analysis, findings, and output decisions
- `.agent-tools/shrinkydink/guard.py` — generated dogfood copy, refreshed through Shrinkydink's apply path
- `tests/test_guard.py` — table-driven behavior, strict contract, no-content-read, and performance tests
- `tests/fixtures/hooks/claude-pre-tool-use.json` — sanitized current Claude payload base
- `tests/fixtures/hooks/codex-pre-tool-use.json` — sanitized current Codex payload base
- `tests/fixtures/hooks/README.md` — fixture provenance, review date, and refresh instructions
- `references/configuration.md` — accurate warn/deny behavior for broad traversal
- `references/platform-support.md` — bounded supported forms, contract caveats, and performance threshold
- `docs/plans/0002-reliable-agentsignore-guard-enforcement.md` — baseline/final results and any implementation deviations recorded by `run`

`scripts/shrinkydink.py`, `.codex/hooks.json`, and Claude settings are not expected to change: the installer already sources the runtime asset and its matchers already cover D-1. Change them only if implementation proves that statement false, and record the deviation before proceeding.

## Risks and follow-ups

- **Conservative false positives are intentional in deny mode.** Slashless ignore rules and ambiguous globs may keep a scoped directory classified as risky. Users can narrow to a direct file or provide exact recognized exclusions. General glob-containment reasoning belongs with pattern-semantics work, not this feature.
- **Shell support remains deliberately bounded.** Wrappers, aliases, dynamic expansion, command substitution, and programs that open paths internally can bypass operand detection. Documentation and messages must continue to call the hook a guardrail.
- **Public hook contracts evolve.** Fixtures pin the reviewed 2026-08-03 common subset and document how to refresh it. The Codex `main`-branch schemas may lead released behavior, so the current Codex manual remains the release-behavior reference; tests should avoid fields documented as parsed-but-unsupported.
- **Timing tests can be noisy.** The D-7 threshold is intentionally generous relative to expected in-process execution. Keep filesystem-walk prohibition as the deterministic performance invariant; if a supported slow platform cannot meet the wall-clock budget, adjust only with evidence and document the new threshold.
- **Broad-operation proof does not replace filesystem isolation.** Even a contract-valid denial applies only when the configured hook runs. Hosted tools, prompt imports/attachments, and unsupported command syntax remain outside enforcement.
- **Follow-up:** brief 0003 should own improvements to Git-ignore equivalence, including richer negation and glob coverage. This plan must not pull those semantics into 0002.
