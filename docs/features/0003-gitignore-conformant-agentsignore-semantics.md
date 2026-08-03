# Gitignore-conformant `.agentsignore` semantics

## Outcome

A user can write `.agentsignore` rules using documented Git-ignore syntax and get predictable, portable matching behavior. Shrinkydink's behavior agrees with a conformance suite and with the established Docker Agent `.agentsignore` convention for the supported syntax, rather than relying on an approximate custom translation.

## Scope

### In scope

- Define the canonical Shrinkydink `.agentsignore` contract in a dedicated reference document.
- Use a mature Git-ignore implementation, or an implementation proven by conformance tests, instead of maintaining an unverified regular-expression approximation.
- Support blank lines, comments, escaped leading `#` and `!`, `*`, `?`, character classes, `**`, leading-slash anchoring, trailing-slash directory-only rules, negation, escaped trailing spaces, and last-matching-rule precedence.
- Correctly implement Git's behavior when a negated child is beneath an excluded parent directory.
- Ensure a directory-only rule such as `build/` does not match a regular file named `build`.
- Normalize path separators and `.` or `..` components before matching, resolve existing symlink components where possible, and refuse to treat paths outside the repository as repository-relative matches.
- Apply the same matcher to direct access checks, broad-search exclusion logic, audit output, and tests.
- Add versioned conformance fixtures containing rules, a synthetic file tree, and expected included or excluded results.
- Include a compatibility fixture based on Docker Agent's published `.agentsignore` examples and document any intentional differences.

### Out of scope

- Adding vendor-specific adapters such as `.clineignore`, `.geminiignore`, `.aiexclude`, or `.cursorignore`.
- Defining whether an effective match should warn, ask, or deny; `.shrinkydink.json` continues to control that policy.
- Treating path matching as enforcement against tools that bypass lifecycle hooks.
- Supporting nested `.agentsignore` files with cascading scope in this iteration; the configured repository-relative ignore file remains canonical.

## Acceptance criteria

- **AC-1** - The repository contains a documented, automated conformance suite for every supported syntax element, including escaped comment and negation markers, escaped trailing spaces, anchoring, `**`, character classes, and last-match precedence.
- **AC-2** - A `build/` rule matches the `build` directory and its descendants but not a regular file named `build`.
- **AC-3** - Negation behavior matches Git for excluded parent directories, and the reference document includes a working example that shows how to re-include a child correctly.
- **AC-4** - Starting a hook from a repository subdirectory produces the same match result as starting it from the repository root for the same target path.
- **AC-5** - Equivalent Windows and POSIX path spellings produce the same repository-relative match result where they refer to the same target.
- **AC-6** - Existing symlink components are normalized before matching, and a path resolving outside the repository is rejected from repository-relative evaluation.
- **AC-7** - Docker Agent's documented example rules produce the same expected include and exclude results in Shrinkydink, with every intentional difference called out in the reference document.
- **AC-8** - The CLI can run the conformance suite in CI without requiring Claude, Codex, or Docker Agent to be installed.

## Constraints and dependencies

- If a third-party parser is adopted, its version must be pinned, its license documented, and its behavior wrapped behind a small internal interface.
- If no dependency is adopted, the implementation must pass the same conformance suite before the README or reference documentation claims Git-ignore compatibility.
- Maintain a migration note for any existing Shrinkydink rule whose behavior changes under conformant matching.
- The ignore file remains a context-control convention, not a security boundary.



## General

-
