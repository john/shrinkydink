# Canonical `.agentsignore` contract

Shrinkydink interprets the configured repository-relative agent ignore file with
Git-ignore semantics for the syntax documented here. The same matcher powers
direct guard checks, conservative broad-search reasoning, audit messages, and
the versioned conformance suite. It is a context-control convention and hook
guardrail, not a filesystem sandbox or secret boundary.

This document defines matching semantics, not Shrinkydink's generated policy.
The automatic default block is deliberately narrow and classified separately
from non-mutating recommendations. Ecosystem rules appear only when marker
filenames are detected; repository-specific rules belong outside the managed
block, where they retain final precedence.

## Supported syntax

- Blank lines have no effect. A leading unescaped `#` starts a comment.
- Escape a leading comment or negation marker as `\#` or `\!` to match it
  literally.
- `*` matches zero or more characters within one path component, `?` matches one
  non-separator character, and bracket expressions such as `[abc]`, `[a-z]`, or
  `[!0-9]` match one character.
- `**` matches across directory boundaries. `docs/**/draft.md` matches with zero
  or more intervening directories.
- A leading `/` anchors the pattern at the repository root. A pattern containing
  no slash matches a file or directory name at any depth.
- A trailing `/` matches directories and their descendants, never a regular file
  with the same name.
- A leading unescaped `!` negates a rule. Rules are evaluated in order and the
  last applicable rule wins, subject to Git's excluded-parent rule below.
- Unescaped trailing spaces are discarded. Escape a significant trailing space
  with `\`.

Patterns use `/` separators. Candidate paths supplied with either `/` or `\`
are normalized before matching.

## Path kinds, precedence, and excluded parents

Matching is typed as either `file` or `directory`. Existing targets derive their
kind from the filesystem without reading content. A direct nonexistent target is
treated as a file unless the tool operation explicitly identifies a directory.
Every ancestor component is evaluated as a directory, so a matched directory
rule applies to its descendants.

Git cannot re-include a child while its parent directory remains excluded. This
does not work:

```gitignore
parent/
!parent/child.txt
```

The first rule excludes `parent` itself, so traversal never reaches the child.
Exclude the parent's contents while leaving the directory traversable instead:

```gitignore
parent/*
!parent/child.txt
```

The conformance suite covers both forms and ordered last-match precedence.

## Normalization and repository boundary

The matcher resolves candidates against the repository root and the hook
payload's working directory. It normalizes POSIX and Windows separators and
collapses `.` and `..` components. Existing symlink components are resolved by
the host filesystem without reading target file content.

Normalization returns a distinct `inside`, `outside`, or `invalid` state. Only
an `inside` path becomes a repository-relative match candidate. A path that
resolves outside the repository is rejected from repository-relative matching;
that rejection does not grant or deny authority to access the external path.
Drive and UNC behavior follows the host platform. Separator-equivalent relative
spellings are portable; foreign drive syntax is not emulated on POSIX systems.

## Broad operations

Direct matching is exact. Broad search analysis is deliberately conservative:
the matcher exposes active rule identities, whether a rule may overlap a scope,
and exact recognized exclusion coverage. A negation can re-include a direct path
without proving an arbitrary traversal safe. Shell expansion, aliases, wrappers,
and general glob-set algebra remain outside the bounded guard model.

## Docker Agent compatibility

The `docker-agent` v1 fixture is based on Docker Agent's first-party
[Ignoring files](https://docs.docker.com/ai/docker-agent/configuration/agentsignore/)
overview and syntax table, reviewed 2026-08-03 and pinned to source snapshot
`docker/docker-agent@7c5b33b1c177311277a3f90362faf4788e88eed2`.
It covers bare names, root anchoring, globs, `build/`,
`docs/**/*.draft.md`, and `!public.key` through the canonical matcher.

Intentional product differences are:

- Shrinkydink uses the one repository-relative file configured by
  `.shrinkydink.json`; it does not discover the nearest parent ignore file.
- Shrinkydink does not automatically hide `.agentsignore` itself unless a rule
  says to do so.
- Shrinkydink enforces only through its documented instruction and lifecycle-hook
  surfaces; it does not inherit Docker Agent's filesystem-tool behavior.
- A trailing inline comment is not Git-ignore syntax. The compatibility rule is
  `!public.key`, without prose appended to that line.

## Migration from the earlier matcher

The former approximation treated a directory-only rule as also matching a
regular file of the same name, stripped escaped trailing spaces, did not accept
escaped leading `!`, allowed a child negation beneath an excluded parent, and
did not expose outside-repository normalization as a distinct result. Those
behaviors now follow this contract. Review custom rules—especially in `deny`
mode—and use the conformance command when migrating.

## Conformance command

Run the packaged fixtures from any working directory; no target repository,
Claude, Codex, Docker Agent, Git, or third-party Python package is required:

```bash
python3 scripts/shrinkydink.py --check-agentsignore-conformance
python3 scripts/shrinkydink.py --check-agentsignore-conformance --json
```

Exit code `0` means every expectation passed, `1` means an expectation mismatch,
and `2` means malformed or missing fixtures or an invalid invocation. The runner
materializes only empty temporary nodes required for path-kind and symlink tests.
