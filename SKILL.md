---
name: shrinkydink
description: Audit and configure a software repository for compact, safer coding-agent context. Use when setting up or validating repository hygiene for Claude Code, OpenAI Codex, or other AGENTS.md-aware agents; creating or repairing .gitignore, .gitattributes, AGENTS.md, CLAUDE.md, .agentsignore, Claude local settings, Codex hooks, or context-usage warnings; reducing accidental ingestion of dependencies, generated files, secrets, and large artifacts; or adding a repeatable CI check for agent-context configuration.
---

# Shrinkydink

Use the bundled deterministic script to audit or configure one repository without replacing unrelated user content. Treat `AGENTS.md` as the shared instruction source and make `CLAUDE.md` import it.

## Workflow

1. Resolve the intended repository root. Prefer the Git top level. Never run against a home directory, filesystem root, or a parent containing multiple unrelated repositories.
2. Run the bundled `scripts/shrinkydink.py` in audit mode, resolving the script path relative to this `SKILL.md`:

   ```bash
   python3 <skill-directory>/scripts/shrinkydink.py --repo <repo-root>
   ```

3. Review conflicts and warnings before writing. Preserve malformed JSON, unmatched managed markers, explicit status-line choices, and unusual existing hook structures; apply aborts before writing when any destination conflicts.
4. When the user requested setup or repair and the audit has no material conflicts, apply the complete validated change set transactionally:

   ```bash
   python3 <skill-directory>/scripts/shrinkydink.py --repo <repo-root> --apply
   ```

   Stop after the audit when the user requested validation only.
5. Verify idempotence and syntax:

   ```bash
   python3 <skill-directory>/scripts/shrinkydink.py --repo <repo-root> --check --no-diff
   git -C <repo-root> status --short
   git -C <repo-root> diff -- .gitignore .gitattributes .agentsignore AGENTS.md CLAUDE.md .shrinkydink.json .claude .codex .agent-tools/shrinkydink
   ```

6. Summarize created, updated, preserved, and conflicted files. State that `.agentsignore` is a cross-agent convention enforced best-effort through instructions and lifecycle hooks, not a universal native standard.

## Safety and preservation rules

- Modify text files only inside shrinkydink-managed blocks. Keep all content outside those blocks byte-for-byte except unavoidable final-newline normalization.
- Prepend managed blocks in order-sensitive ignore and attributes files so later repository-owned rules retain precedence.
- Merge JSON objects and hook arrays structurally. Never replace an invalid JSON file or a non-object hook structure.
- Validate existing and generated Codex TOML when `tomllib` is available; preserve invalid TOML and report a conflict.
- Refuse to replace symbolic links and reject managed paths whose existing parent components resolve outside the repository. Preserve existing file modes and use owner-only permissions for newly created Claude local settings where supported.
- Preserve an existing Claude status line or Codex status line that the script cannot safely compose with. Show the manual integration needed.
- Default `.agentsignore` to `warn`. Use `deny` only when the user explicitly requests hard blocking and understands that intentional exceptions require changing `.shrinkydink.json`.
- Do not add broad ignores for source, lockfiles, fixtures, migrations, documentation, images, or PDFs merely to make the repository smaller.
- Do not remove tracked files, run `git rm --cached`, rewrite Git history, or commit changes unless explicitly requested.
- Treat hook enforcement as a guardrail. Direct prompt attachments, Claude `@` imports, hosted tools, shell indirection, and specialized tools may bypass it.

## Configuration

Use command-line overrides when requested:

```bash
python3 <skill-directory>/scripts/shrinkydink.py \
  --repo <repo-root> --apply \
  --context-warning-percent 75 \
  --ignore-mode warn \
  --large-file-warning-kb 512
```

Use `--no-claude` or `--no-codex` to omit one platform. Use `--json` for machine-readable output. Use `--check` in CI; exit code `1` means drift or a conflict, and exit code `2` means invocation failure.

Read [references/configuration.md](references/configuration.md) for the generated files, pattern semantics, and options. Read [references/platform-support.md](references/platform-support.md) before explaining cross-agent guarantees or troubleshooting hooks. Read [references/installation.md](references/installation.md) when installing this skill in Claude Code or Codex.

## Result standard

A successful setup should leave:

- stack-aware `.gitignore` rules and conservative `.gitattributes` normalization;
- shared context guidance in `AGENTS.md`, imported by `CLAUDE.md`;
- a configurable `.agentsignore` plus lightweight Python guard scripts;
- Claude local PreToolUse and exact context-percentage status warnings when no prior status line conflicts;
- Codex project hooks, a visible `context-remaining` footer, and a warning before compaction;
- a committed `.shrinkydink.json` policy file and a warning for unusually large tracked files;
- a second `--check` run with no drift.
