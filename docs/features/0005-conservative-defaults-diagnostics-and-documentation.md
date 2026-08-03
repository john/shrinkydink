# Conservative defaults, actionable diagnostics, and user documentation

## Outcome

Shrinkydink makes only high-confidence automatic changes, explains why each change or recommendation exists, and gives users an accurate account of what the tool protects and what it does not. Broad exclusions that may hide useful versioned source become explicit recommendations rather than silent defaults, and the README reflects all user-relevant behavior delivered through briefs 0001-0005.

## Scope

### In scope

- Classify generated ignore rules as high-confidence automatic defaults, ecosystem-specific defaults, or repository-specific recommendations.
- Keep automatic `.agentsignore` additions narrow: version-control internals, local agent state, obvious local secrets, detected dependency stores, caches, and generated products whose source equivalent is normally present.
- Stop automatically adding broad or ambiguous rules such as all `vendor/`, `build/`, `out/`, `*.db`, `*.map`, `*.jar`, and `*.bin` paths unless the detected ecosystem makes a rule high confidence.
- Inspect tracked filenames and sizes without reading file contents, and report likely large, generated, binary, database, archive, or secret-like paths as recommendations with a reason and suggested action.
- Warn distinctly when a secret-like path is already tracked, explaining that `.gitignore` does not untrack it and that credential rotation may be necessary, without displaying file contents.
- Separate planned changes, conflicts, warnings, and recommendations in text and JSON reports using stable fields suitable for CI.
- Describe `.gitattributes` normalization as Git behavior rather than LLM access control, and avoid introducing broad normalization into an established repository without an explicit policy or clearly surfaced change.
- Add examples for a new repository, an established repository with existing configuration, and a repository with intentionally versioned large fixtures.
- Update the root README and relevant reference documents with all information of value to users from briefs 0001-0005, including the safety and rollback model, custom ignore paths, exact `.agentsignore` semantics, `warn` and `deny` behavior, known bypasses, shared Claude and Codex files, supported platforms, default versus recommended exclusions, upgrade notes, and verification commands.

### Out of scope

- Reading file contents to perform entropy analysis or comprehensive secret scanning.
- Automatically deleting, untracking, rotating, or rewriting the history of a suspected secret.
- Automatically accepting repository-specific recommendations.
- Generating ignore adapters for other agent products.
- Claiming that `.gitignore`, `.gitattributes`, `.agentsignore`, or hooks alone provide a complete security boundary.

## Acceptance criteria

- **AC-1** - On a repository with no detected ecosystem, Shrinkydink's automatic `.agentsignore` block contains only documented high-confidence rules and does not automatically exclude the ambiguous broad path and extension examples listed in scope.
- **AC-2** - Ecosystem-specific automatic rules are added only when the corresponding ecosystem is detected, and the report identifies the marker that caused each ecosystem to be detected.
- **AC-3** - Tracked large or ambiguous files are listed as recommendations with path, size when available, reason, and a copyable suggested rule; the files are not added to `.agentsignore` automatically.
- **AC-4** - A tracked secret-like filename produces a high-severity warning that explains the limits of `.gitignore` and recommends appropriate remediation without opening or printing the file.
- **AC-5** - JSON output exposes separate stable arrays or status fields for changes, conflicts, warnings, and recommendations, and tests verify compatibility of that structure.
- **AC-6** - Existing user-owned `.gitignore`, `.gitattributes`, and `.agentsignore` rules remain intact and retain their documented precedence after apply.
- **AC-7** - The README accurately documents every user-visible behavior delivered by briefs 0001-0005, includes a clear statement that the guardrails are not a sandbox, and contains tested installation, audit, apply, check, and upgrade examples.
- **AC-8** - The README and CLI use consistent terminology for automatic defaults, recommendations, warnings, denials, shared configuration, and local configuration.

## Constraints and dependencies

- The tool must not read the contents of files merely to classify them for recommendations in this brief.
- Recommendations should favor false negatives over hiding source or fixtures that may be necessary to complete a task.
- Documentation examples must be exercised by tests or a release checklist so command names, paths, and generated-file descriptions do not drift.
- `warn` remains the default policy; any stronger claim must be supported by the enforcement and conformance work in briefs 0002 and 0003.
- Changes to established `.gitattributes` behavior must be surfaced prominently because line-ending normalization can affect subsequently staged files.
