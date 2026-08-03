# Reliable `.agentsignore` guard enforcement

## Outcome

For the file-oriented Claude and Codex tools Shrinkydink claims to support, `warn` mode reliably identifies likely access to ignored paths and `deny` mode blocks direct ignored-path access and repository-wide operations that could traverse ignored content. Common bare filenames and list-valued tool inputs no longer bypass the guard.

## Scope

### In scope

- Extract candidate paths from scalar path fields, nested objects, and list-valued path fields in supported hook payloads.
- Recognize bare relative filenames as paths when they occur in path-bearing tool fields or as operands to common filesystem-oriented shell commands.
- Continue recognizing paths in `apply_patch` headers, absolute paths, relative paths, glob inputs, and commands issued from repository subdirectories.
- Distinguish a content-search expression from a path argument so ordinary search terms are not treated as filenames.
- Treat an unscoped repository-wide `Grep`, `Glob`, recursive shell search, or recursive listing as a possible traversal of ignored content.
- In `warn` mode, allow a detected operation while returning concise additional context that identifies rules and recommends a narrower operation.
- In `deny` mode, block both direct ignored-path matches and broad searches that can traverse ignored paths unless the operation demonstrably excludes every ignored path.
- Validate the emitted hook response against the current Claude and Codex `PreToolUse` contracts.
- Add a table-driven test suite covering every supported tool and representative payload shape.

### Out of scope

- Fully parsing arbitrary shell programs, aliases, functions, `eval`, command substitution, dynamic variable expansion, or programs that open files internally.
- Preventing access through hosted tools, language servers, direct prompt attachments, explicit file imports, or agent implementations that do not execute the configured hook.
- Changing `.agentsignore` pattern semantics; that work belongs to brief 0003.
- Describing hook enforcement as a sandbox or a complete secret-protection boundary.

## Acceptance criteria

- **AC-1** - In both Claude-style and Codex-style fixtures, direct tool inputs containing a matching path are detected whether the path is a scalar, nested value, or member of a list such as `paths` or `files`.
- **AC-2** - Shell commands including `cat private.pem`, `head private.pem`, `cp private.pem copy.pem`, and `rm build/output.bin` identify their relevant path operands even when an operand contains no slash.
- **AC-3** - Search expressions such as `rg private.pem src/` do not treat `private.pem` as a path merely because it resembles a filename; the explicitly scoped `src/` target determines whether the operation is broad.
- **AC-4** - In `deny` mode, an unscoped repository-wide search or recursive listing is blocked when the active ignore file contains at least one effective exclusion. The response explains that the operation must be narrowed or explicitly exclude ignored paths.
- **AC-5** - In `warn` mode, the same broad operation proceeds but supplies a warning to the user and model without exposing contents from an ignored file.
- **AC-6** - A direct nonmatching path and a narrowly scoped operation outside ignored paths proceed without a warning or denial.
- **AC-7** - Denials produced by the guard are recognized as blocking decisions by current Claude and Codex hook-output fixtures; malformed output fails tests rather than silently degrading to a warning.
- **AC-8** - Guard execution remains fast enough for interactive use, with a documented test threshold and no repository-wide filesystem walk on each hook invocation.

## Constraints and dependencies

- `warn` remains the default mode.
- Messages may reveal a matching path and rule but must never read or include the matched file's contents.
- Detection should favor bounded, testable support for common tools over claims that arbitrary shell syntax is understood.
- Hook payload fixtures should be sourced from current public schemas or captured, sanitized examples and retained in the repository so behavior changes are reviewable.
