# Installation and invocation

The ZIP contains one skill directory named `shrinkydink`.

## Claude Code

Install for one repository by copying the directory to:

```text
<repo>/.claude/skills/shrinkydink/
```

Install for the current user by copying it to:

```text
~/.claude/skills/shrinkydink/
```

Start or restart Claude Code, then invoke:

```text
/shrinkydink
```

Ask for audit-only behavior explicitly when no writes are desired.

## OpenAI Codex

Install for one repository by copying the directory to:

```text
<repo>/.agents/skills/shrinkydink/
```

Install for the current user by copying it to:

```text
~/.agents/skills/shrinkydink/
```

Start or restart Codex, then invoke the skill explicitly as:

```text
$shrinkydink
```

Codex uses `$skill-name` rather than Claude Code's slash-command spelling.

## Direct script use

The deterministic audit/configuration engine can also be run without agent invocation:

```bash
python3 shrinkydink/scripts/shrinkydink.py --repo path/to/repo
python3 shrinkydink/scripts/shrinkydink.py --repo path/to/repo --apply
python3 shrinkydink/scripts/shrinkydink.py --repo path/to/repo --check --no-diff
```
