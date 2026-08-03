# Plan: Gitignore-conformant `.agentsignore` semantics

Source brief: docs/features/0003-gitignore-conformant-agentsignore-semantics.md
Status: implemented
Planned against commit: 07ae6fb79eb5b4fa816d5bad70e858b1deb59fb2
Base commit: 07ae6fb79eb5b4fa816d5bad70e858b1deb59fb2

## Outcome

Replace Shrinkydink's approximate regular-expression translation with one dependency-free, Git-ignore-conformant matcher used by direct path checks, broad-operation reasoning, the conformance-audit CLI, and tests. Publish the supported contract and migration notes, and prove it with versioned fixtures that cover the supported syntax plus Docker Agent's published `.agentsignore` example.

## Scope

### In scope

- Define the canonical Shrinkydink `.agentsignore` contract in `references/agentsignore.md`, including syntax, path-kind handling, normalization, precedence, excluded-parent negation, portability, compatibility, and migration behavior.
- Introduce a small standard-library matcher module that parses ordered rules once and exposes direct-path matching plus conservative broad-scope/exclusion queries.
- Support blank lines, comments, escaped leading `#` and `!`, `*`, `?`, character classes, `**`, leading-slash anchoring, trailing-slash directory-only rules, negation, escaped trailing spaces, and last-matching-rule precedence.
- Preserve Git's excluded-parent behavior: a negated child cannot be re-included while an ancestor directory itself remains excluded; document and test the working `parent/*` then `!parent/child` form.
- Distinguish regular files from directories so `build/` matches a directory and its descendants but not a regular file named `build`.
- Normalize relative, absolute, Windows-separator, POSIX-separator, `.`, and `..` spellings against the repository and hook `cwd`; resolve existing symlink components; reject outside-repository paths from repository-relative matching.
- Route direct guard findings and broad-search rule/exclusion reasoning through the same matcher interface without weakening the conservative behavior introduced by brief 0002.
- Add a standalone `--check-agentsignore-conformance` CLI mode with deterministic text and JSON reports and CI-appropriate exit codes.
- Add versioned, content-free synthetic-tree fixtures and a Docker Agent compatibility fixture with pinned provenance.
- Install the matcher beside the generated guard and retain byte-identical source/dogfood runtime copies.

### Out of scope

- Vendor-specific ignore adapters, nested/cascading `.agentsignore` discovery, or changing the configured repository-relative ignore-file location.
- Changing `warn`, `deny`, or `off` policy semantics, hook coverage, or the fact that lifecycle hooks are guardrails rather than a security boundary.
- General shell parsing, arbitrary glob-set algebra, filesystem sandboxing, or traversal of ignored contents.
- Depending on Git, Claude, Codex, Docker Agent, or a third-party Python package at runtime.
- Reinterpreting `.gitignore`, `.dockerignore`, or generated default-rule ownership outside the documented `.agentsignore` migration.
- Running the conformance suite automatically during ordinary repository audit/check/apply; the new explicit CLI mode is the conformance-audit output surface.

## Assumptions and decisions

- **D-1 — Add an explicit CLI mode.** The user preferred a CLI surface and delegated the exact choice. Add `--check-agentsignore-conformance` to the existing mutually exclusive mode group. It runs packaged versioned fixtures without resolving or mutating a target repository, supports `--json`, prints a concise text report otherwise, returns `0` for full conformance, `1` for expectation mismatches, and `2` for malformed/missing fixtures or invalid invocation. Repository mutation/configuration overrides are invalid with this mode.
- **D-2 — Keep ordinary audit/check focused.** The brief's audit-output requirement is satisfied by the explicit conformance-audit mode, whose report is produced from the canonical matcher. Ordinary audit/check/apply output and performance remain unchanged except for documentation of the new option.
- **D-3 — Use a proven internal implementation, not a dependency.** The repository has no package manifest and its generated hooks currently require only Python 3.9 standard-library support. Add `assets/runtime/agentsignore.py` as the canonical matcher and install it beside `guard.py`; do not add packaging, license, or dependency-management machinery solely for this feature.
- **D-4 — Make path kind explicit.** The matcher accepts a normalized repository-relative path and an explicit kind (`file` or `directory`). Existing filesystem entries derive the kind without reading content; search scopes and directory-oriented tool operations supply a directory hint; unknown/nonexistent direct write targets default to file unless the tool operation explicitly creates or targets a directory. Ancestor components are always evaluated as directories.
- **D-5 — Normalize before matching and fail closed at the interface boundary.** Convert separators, collapse `.`/`..`, resolve existing symlink components using the host filesystem, and compare resolved paths to the resolved repository root. The normalization result distinguishes `inside`, `outside`, and `invalid`; outside/invalid paths are never converted into repository-relative candidates or fed to ignore matching. This is a matching rejection, not authority to block access outside the repository.
- **D-6 — Centralize matcher-owned broad reasoning.** Replace `effective_ignore_rules`, `rule_may_match_under`, and direct regex access with matcher methods that expose ordered rules, direct match results, conservative `may_ignore_under(scope)`, and exact recognized exclusion coverage. Uncertainty remains broad; negations may reduce a direct match but do not prove a broad traversal safe unless the matcher's conservative query can prove it.
- **D-7 — Version fixtures as data.** Use `tests/fixtures/agentsignore/v1/` with rule files plus JSON manifests describing synthetic path, type, optional symlink target, and expected included/excluded/rejected result. The runner materializes only temporary, content-free nodes when filesystem behavior is required; no secret-like fixture contents are committed or emitted.
- **D-8 — Pin Docker compatibility provenance.** Base the compatibility fixture on Docker Agent's first-party `Ignoring files` overview example and syntax table at `https://docs.docker.com/ai/docker-agent/configuration/agentsignore/`, reviewed 2026-08-03, with source snapshot `docker/docker-agent@7c5b33b1c177311277a3f90362faf4788e88eed2`. Record that Shrinkydink uses one configured repository-relative file rather than nearest-parent discovery, does not automatically hide `.agentsignore` itself unless configured, and enforces only through its documented hook surface. Treat the trailing inline comment in Docker's longer example as prose, not Git-ignore syntax; the compatibility rule keeps `!public.key` without an inline comment.
- **D-9 — Preserve brief 0002 behavior.** Keep path-field extraction, bounded shell parsing, user/model warning channels, deny decisions, explicit-exclusion proof, truncation, and no-content-read/performance guarantees unless conformance requires a narrowly documented adjustment.
- **D-10 — Preserve unrelated work.** Planning occurred on `feat/0002-reliable-agentsignore-guard-enforcement` at `07ae6fb`, while `origin/main` is the default branch. The worktree contains untracked `.agents/`, `.claude/`, and the 0003 brief. No existing 0003 branch or pull request was found. `run` must preserve these user-owned paths, establish and record its base per the feature workflow, and never clean, stash, overwrite, or commit unrelated work.

## Planning-time implementation findings

- `assets/runtime/guard.py::parse_rules` calls `rstrip()`, which loses escaped trailing-space information; it handles escaped `#` but not escaped `!`, and its comment detection and whitespace treatment are not a canonical Git-ignore parser.
- `translate_gitignore` records `directory_only` but emits the same descendant-capable regex for file and directory rules. Consequently `build/` can match a regular file named `build`, contrary to AC-2.
- `match_rule` applies last-match precedence only to the final path string. It does not evaluate excluded directory ancestors, so a negated child can be incorrectly re-included beneath an excluded parent.
- `to_relative` already uses hook `cwd` and `Path.resolve(strict=False)`, which is a useful base for subdirectory and existing-symlink normalization, but its `None` result conflates root, invalid, and outside-repository candidates and its Windows handling needs explicit coverage.
- Broad-operation helpers currently reason over `Rule.regex` and an exact-identity approximation in `effective_ignore_rules`. These call sites must move behind the canonical matcher so direct and broad behavior cannot drift.
- `scripts/shrinkydink.py::runtime_asset` already copies runtime assets transactionally, but `build_plan` installs only `guard.py`, `claude_status.py`, and `codex_precompact.py`. The matcher must be added to the guard runtime set and regenerated through the normal apply path.
- `tests/test_guard.py` has strong hook-contract, direct/broad operation, no-content-read, and performance coverage, but no table-driven syntax conformance or file-versus-directory model.
- `references/configuration.md` currently describes an intentionally approximate practical subset. It must defer to the new canonical reference and carry a concise migration notice.
- The current CLI resolves a repository before dispatching any mode. The conformance mode must dispatch before `resolve_repo` so CI can validate the packaged matcher independently of a target repository.

## Acceptance-criteria traceability

| ID | Acceptance criterion | Implementation | Verification | Status |
|---|---|---|---|---|
| AC-1 | The repository contains a documented, automated conformance suite for every supported syntax element, including escaped comment and negation markers, escaped trailing spaces, anchoring, `**`, character classes, and last-match precedence. | `references/agentsignore.md`; `assets/runtime/agentsignore.py`; `tests/fixtures/agentsignore/v1/syntax.agentsignore`, `tree.json`, and `expected.json`; `tests/test_agentsignore_conformance.py` | Conformance CLI passed all 25 canonical syntax cases; focused module passed 7 tests | pass |
| AC-2 | A `build/` rule matches the `build` directory and its descendants but not a regular file named `build`. | Explicit target kinds and ancestor-directory evaluation in `AgentsIgnoreMatcher.match`; guard kind inference | Canonical cases `directory-only-file`, `directory-only-directory`, and `directory-descendant` passed; guard integration suite passed | pass |
| AC-3 | Negation behavior matches Git for excluded parent directories, and the reference document includes a working example that shows how to re-include a child correctly. | Ordered ancestor evaluation in `AgentsIgnoreMatcher.match`; contrasting examples in `references/agentsignore.md` | Canonical blocked/working cases and focused `test_directory_kind_and_excluded_parent_semantics` passed | pass |
| AC-4 | Starting a hook from a repository subdirectory produces the same match result as starting it from the repository root for the same target path. | `AgentsIgnoreMatcher.normalize` uses root plus payload `cwd`; installed guard retains root discovery | Canonical `subdirectory-cwd`, guard path test, and installed-guard subprocess from a child cwd passed | pass |
| AC-5 | Equivalent Windows and POSIX path spellings produce the same repository-relative match result where they refer to the same target. | Candidate separators normalize before host path resolution; drive/UNC behavior remains host-native | Canonical `windows-separators` and focused normalization test passed on POSIX; no foreign drive emulation claimed | pass |
| AC-6 | Existing symlink components are normalized before matching, and a path resolving outside the repository is rejected from repository-relative evaluation. | Resolved-root containment with explicit `inside`/`outside`/`invalid` normalization states | Canonical inside/outside symlink cases and focused matcher/guard symlink tests passed; 0 platform skips | pass |
| AC-7 | Docker Agent's documented example rules produce the same expected include and exclude results in Shrinkydink, with every intentional difference called out in the reference document. | Versioned Docker rules/expectations plus pinned provenance and difference list in `references/agentsignore.md` | Docker compatibility suite passed 11/11 cases | pass |
| AC-8 | The CLI can run the conformance suite in CI without requiring Claude, Codex, or Docker Agent to be installed. | Early-dispatched text/JSON `--check-agentsignore-conformance` mode using only Python standard library and temporary fixtures | Text and JSON commands passed outside a repository; tests covered mismatch=1, malformed/invalid=2, and no cwd writes | pass |

## Verification

Per the `feat plan` workflow, no baseline was executed during planning; `run` records baseline and final results.

| Command | Purpose | Baseline result | Final result |
|---|---|---|---|
| `python3 scripts/shrinkydink.py --check-agentsignore-conformance` | Public CI entry point for all versioned conformance and Docker compatibility fixtures | unavailable (exit 2); CLI rejected the unrecognized option | pass; 36/36 cases, 0 skipped |
| `python3 scripts/shrinkydink.py --check-agentsignore-conformance --json` | Deterministic machine-readable conformance report and exit behavior | unavailable (exit 2); CLI rejected the unrecognized option | pass; deterministic JSON reported 36 passed, 0 failed, 0 skipped |
| `python3 -m unittest tests.test_agentsignore_conformance -v` | Focused parser, matcher, normalization, path-kind, symlink, fixture, and CLI-runner coverage | unavailable (exit 1); test module does not exist | pass; 7 tests |
| `python3 -m unittest tests.test_guard -v` | Guard integration, direct/broad behavior, hook contracts, no-content-read, and performance | pass; 15 tests | pass; 16 tests |
| `python3 -m unittest tests.test_shrinkydink -v` | CLI dispatch, transactional installation, generated asset set, and idempotence | pass; 12 tests | pass; 12 tests |
| `python3 -m unittest discover -s tests -t . -v` | Full regression suite | pass; 27 tests | pass; 35 tests |
| `python3 scripts/shrinkydink.py --repo . --check --no-diff` | Repository self-consistency after regenerating installed runtime assets and documentation | pass with pre-existing Python 3.11+ TOML-validation warning | pass with the same pre-existing Python 3.11+ TOML-validation warning |
| `cmp -s assets/runtime/guard.py .agent-tools/shrinkydink/guard.py && cmp -s assets/runtime/agentsignore.py .agent-tools/shrinkydink/agentsignore.py` | Prove both committed dogfood runtime files are byte-identical to canonical assets | unavailable (exit 2); new matcher files do not exist | pass |
| `git diff --check` | Reject whitespace errors in code, fixtures, tests, docs, and the plan | pass | pass |

## Run notes and deviations

- No material scope or acceptance-criteria deviations were required. A narrow
  repository-owned `.gitattributes` rule was added for
  `tests/fixtures/agentsignore/v1/syntax.agentsignore` so its required literal
  escaped trailing-space case is not reported as an error by `git diff --check`;
  all other files retain normal end-of-line whitespace checks.
- The branch started and the baseline ran at the recorded base commit. Before final verification it was fast-forwarded to current `origin/main` (`88add6c`), which contained the already-merged feature 0002 and a repository README rename/update; the full verification matrix was rerun afterward.
- The user-owned untracked paths `.agents/skills/feat` and `.claude/skills/feat` were explicitly excluded from all reads, edits, staging, and commits.
- This feature has no visual user interface; screenshot or browser-based visual verification is not applicable.

## Implementation steps

1. **Define the fixture contract and canonical reference.** Add `references/agentsignore.md` and `tests/fixtures/agentsignore/v1/README.md` describing fixture schema/versioning, normative Git-ignore behavior, path kinds, normalization states, excluded-parent re-inclusion, and the boundary between matching and policy enforcement.
2. **Create the matcher module and stable interface.** Add `assets/runtime/agentsignore.py` with immutable parsed-rule/match/normalization data types and a small `AgentsIgnoreMatcher` interface for parsing text/files, normalizing candidates, matching typed paths, exposing display-safe rule identities, conservative scope checks, and exact supported exclusion coverage. Keep imports Python 3.9 standard-library-only.
3. **Implement conformant parsing.** Parse lines without destroying significant escapes; distinguish unescaped comments/negation from literal leading markers; remove only unescaped trailing spaces; retain ordered rule text for messages; classify anchored, slashless, directory-only, and negated rules; compile `*`, `?`, character classes, and all supported `**` positions with component-aware semantics.
4. **Implement typed path and ancestor matching.** Evaluate normalized components with explicit target kind, apply root anchoring and slashless-any-depth rules, carry directory matches to descendants, enforce last-match precedence, and prevent child negations from bypassing an excluded ancestor. Add the documented `parent/*` plus `!parent/child` working form.
5. **Harden normalization.** Replace `to_relative`'s ambiguous optional string with structured root/cwd normalization that canonicalizes separators and dot components, handles absolute and platform drive spellings, resolves existing symlink prefixes without reading file contents, and rejects outside/invalid candidates. Preserve root-target detection for broad operations.
6. **Integrate direct guard checks.** Import the sibling matcher from `guard.py`, attach file/directory hints from existing files and tool semantics, replace `parse_rules`/`translate_gitignore`/`match_rule`, and keep messages limited to normalized paths and original rule text. Add integration cases for directory-only rules, escaped markers/spaces, precedence, subdirectory `cwd`, separators, symlinks, and outside paths.
7. **Integrate broad-operation reasoning.** Move active-rule, scope-overlap, and explicit-exclusion decisions behind matcher methods. Retain the brief-0002 conservative rule that uncertain overlap is broad and every relevant exclusion must be covered; add cases where negation changes direct matching without incorrectly proving a repository-wide scan safe.
8. **Build the versioned conformance runner.** Load fixture manifests defensively, materialize required temporary directories/files/symlinks with empty content, run every case through the canonical matcher, and return structured per-suite/pass/fail/skip/error results. Malformed fixtures are execution errors, expectation mismatches are conformance failures, and platform-unavailable symlink creation is reported rather than silently counted as pass.
9. **Add the CLI conformance-audit mode.** Extend argument parsing and early `main` dispatch for `--check-agentsignore-conformance`; reject incompatible mutation/configuration flags; support concise text and stable JSON reports; avoid repository resolution and writes; implement D-1 exit codes; and document the command as the CI entry point.
10. **Add syntax and Docker fixtures.** Populate the v1 synthetic tree and expectations for every listed syntax/normalization behavior. Add a separately named Docker Agent rule/expectation set based on the pinned first-party overview example and syntax table, including bare names, anchored names, globs, `build/`, `docs/**/*.draft.md`, and `!public.key`.
11. **Expand automated tests.** Add `tests/test_agentsignore_conformance.py` for fixture execution, focused edge cases, CLI text/JSON/exit behavior, no-repository execution, and no writes. Update `tests/test_guard.py` for matcher integration and retain every brief-0002 contract/performance assertion. Update `tests/test_shrinkydink.py` for the additional installed runtime asset, apply/check idempotence, and CLI option compatibility.
12. **Update product documentation and migration guidance.** Make `references/configuration.md` defer to the canonical contract, add old-versus-new behavior notes for directory-only files, escaped markers/spaces, excluded-parent negation, and normalization, and document the CLI mode. Update `references/platform-support.md` for typed matching, symlink/outside handling, and Docker differences. Link the canonical reference from `SKILL.md` without claiming a sandbox or universal native support.
13. **Regenerate dogfood assets and verify.** Run `python3 scripts/shrinkydink.py --repo . --apply` as an implementation step so `.agent-tools/shrinkydink/guard.py` and the new sibling matcher are produced transactionally. Run every verification command above, record baseline/final results and any implementation deviation in this plan, and preserve all unrelated work.

## Files likely to change

- `assets/runtime/agentsignore.py` — canonical parser, normalizer, typed matcher, and broad-scope interface
- `assets/runtime/guard.py` — matcher integration and path-kind/tool-context adaptation
- `.agent-tools/shrinkydink/agentsignore.py` — generated dogfood matcher copy
- `.agent-tools/shrinkydink/guard.py` — regenerated dogfood guard copy
- `scripts/shrinkydink.py` — runtime installation plus conformance CLI dispatch/reporting
- `tests/fixtures/agentsignore/v1/README.md` — fixture schema, versioning, and provenance
- `tests/fixtures/agentsignore/v1/syntax.agentsignore` — canonical syntax rules
- `tests/fixtures/agentsignore/v1/tree.json` — content-free synthetic path/type/symlink model
- `tests/fixtures/agentsignore/v1/expected.json` — syntax and normalization expectations
- `tests/fixtures/agentsignore/v1/docker-agent.agentsignore` — pinned first-party example rules
- `tests/fixtures/agentsignore/v1/docker-agent-expected.json` — Docker compatibility expectations
- `tests/test_agentsignore_conformance.py` — matcher, fixture-runner, normalization, and CLI-mode coverage
- `tests/test_guard.py` — direct/broad guard integration and regression coverage
- `tests/test_shrinkydink.py` — installed-asset and CLI dispatch/idempotence coverage
- `references/agentsignore.md` — canonical syntax, examples, compatibility, and migration contract
- `references/configuration.md` — reference link, CLI option, and migration summary
- `references/platform-support.md` — normalization, portability, and enforcement limits
- `SKILL.md` — route users to the canonical `.agentsignore` reference
- `docs/plans/0003-gitignore-conformant-agentsignore-semantics.md` — baseline/final results and deviations recorded by `run`

Exact fixture filenames may be consolidated if one manifest cleanly preserves separate canonical and Docker suites; retain the versioned directory, explicit provenance, synthetic node kinds, and independently reportable expectations.

## Risks and follow-ups

- **Git-ignore edge cases are subtle.** Component-aware `**`, bracket expressions, escaping, directory ancestry, and whitespace must be fixture-driven. Unsupported syntax must be documented rather than silently advertised as full byte-for-byte Git support.
- **Path kind can be unknown before creation.** D-4 deliberately defaults unknown direct targets to files unless tool semantics provide a directory hint. This avoids making `build/` block creation of a regular file named `build`; unsupported shell commands remain outside the hook's bounded model.
- **Windows path handling is host-sensitive.** Relative separator equivalence can be tested everywhere; drive/UNC and symlink cases must run on capable hosts and report platform skips explicitly. Do not emulate a foreign filesystem in a way that creates false conformance confidence.
- **Negation complicates broad-search proof.** Direct matching can be exact while scope-overlap analysis remains conservative. False-positive warnings/denials are preferable to claiming a broad operation excludes every ignored path when that cannot be proved.
- **Docker Agent compatibility is scoped.** The fixture proves matching outcomes for the published example, not parity with Docker's nearest-file discovery, automatic hiding, filesystem-tool refusal surface, or permission UI.
- **Generated sibling imports must be reliable.** Test direct execution of installed `guard.py` from both repository root and subdirectories so adding `agentsignore.py` does not depend on the caller's `PYTHONPATH`.
- **Conformance mode becomes a public interface.** Keep its JSON schema and exit codes documented and deterministic; future fixture versions should be additive or explicitly versioned.
- **No security-boundary claim.** Conformant path matching does not cover hosted tools, prompt attachments, arbitrary shell indirection, or tools that bypass lifecycle hooks.
