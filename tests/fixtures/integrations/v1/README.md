# Agent integration fixture contract v1

These synthetic scenarios cover committed Claude project settings, preserved or migrated Claude local settings, Codex project hooks, nested working directories, and native-Windows command rendering. They contain no user, transcript, repository, or secret data.

Reviewed 2026-08-03 against the released configuration documented at:

- https://code.claude.com/docs/en/settings
- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/permissions
- https://developers.openai.com/codex/config-advanced#hooks
- https://developers.openai.com/codex/config-basic#configuration-precedence
- https://github.com/openai/codex/blob/main/codex-rs/hooks/schema/generated/hooks.schema.json

The tests validate only the subset emitted by Shrinkydink: project hook event arrays, command handlers and platform overrides, Claude `Read`/`Edit` deny rules, status-line preservation, additive audit metadata, and TOML parsing when the running Python provides `tomllib`. Generated schemas from a product development branch may lead a released client, so released documentation takes precedence.

Refresh this fixture version only after reviewing current released client behavior. Add a new version when an emitted field or ownership signature changes incompatibly.
