# Hook contract fixtures

These sanitized `PreToolUse` payloads were reviewed on 2026-08-03 against:

- Claude Code's [hooks reference](https://code.claude.com/docs/en/hooks), especially the common input, `PreToolUse` input, and decision-control sections.
- The current Codex hooks manual at [developers.openai.com](https://developers.openai.com/codex/config-advanced#hooks).
- Codex's generated [`pre-tool-use.command.input.schema.json`](https://github.com/openai/codex/blob/main/codex-rs/hooks/schema/generated/pre-tool-use.command.input.schema.json) and [`pre-tool-use.command.output.schema.json`](https://github.com/openai/codex/blob/main/codex-rs/hooks/schema/generated/pre-tool-use.command.output.schema.json).

The fixtures retain the documented platform-specific envelope while tests replace `cwd`, `tool_name`, and `tool_input`. They contain no real transcript, model, session, tool-call, repository, or user data.

When refreshing them, use the released behavior documented by each product. Codex's `main`-branch generated schemas can contain fields ahead of the current release, so do not add a field that the released hooks manual describes as unsupported.
