# Safe transactional repository writes

## Outcome

Running Shrinkydink against a repository cannot write outside that repository, and `--apply` either completes the entire validated change set or leaves the repository as it was. A configured alternative path for `.agentsignore` is honored consistently by planning, generation, checking, and runtime enforcement.

## Scope

### In scope

- Resolve the selected repository root once and validate every managed destination against that resolved root before any write occurs.
- Reject a destination when the file itself or any existing parent component is a symbolic link that could redirect the write outside the repository.
- Use the effective `agentsignore` value from `.shrinkydink.json` everywhere instead of separately hard-coding `.agentsignore` during generation.
- Complete a full preflight before writing. By default, any conflict, invalid configuration, unsafe path, or unreadable target prevents all writes.
- Stage every new file body before replacing any destination. If a replacement fails after writes begin, restore every destination already changed during that run.
- Preserve existing file modes and the intended restrictive mode for newly created local settings.
- Add automated regression tests for custom ignore paths, unsafe symlinked parents, invalid configuration, partial-write failures, permission preservation, and idempotence.

### Out of scope

- Providing a security sandbox for the coding agent after repository setup.
- Making the operation crash-consistent across power loss or forced process termination.
- Modifying Git history, removing tracked files, committing changes, or operating on multiple repositories in one invocation.

## Acceptance criteria

- **AC-1** - Audit and check modes perform no filesystem writes, including creation of temporary files inside the target repository.
- **AC-2** - When `.shrinkydink.json` sets `"agentsignore": "config/agent-ignore"`, Shrinkydink creates, checks, and the runtime guard reads `config/agent-ignore`; it does not create or consult a second root `.agentsignore`.
- **AC-3** - If `.claude`, `.codex`, `.agent-tools`, or another parent of a planned destination is a symlink that resolves outside the repository, the run reports a conflict and creates or changes nothing outside the repository.
- **AC-4** - If any planned change is conflicted or invalid, a normal `--apply` run changes none of the otherwise valid destinations.
- **AC-5** - A simulated failure during the replacement phase restores all destinations already changed by that run and exits nonzero with a clear report of the failure and restoration result.
- **AC-6** - Existing file permissions are retained, newly created Claude local settings remain owner-only where POSIX modes are supported, and executable runtime helpers remain executable.
- **AC-7** - After a successful apply, an immediate `--check --no-diff` reports no drift and exits successfully.

## Constraints and dependencies

- Preserve all user-owned content outside Shrinkydink-managed blocks.
- Prefer standard-library implementation unless an external dependency materially improves correctness and is explicitly justified, pinned, and licensed compatibly.
- Filesystems differ in symlink and permission behavior. Tests must cover POSIX behavior and skip with an explicit reason where the host cannot represent a case.
- Rollback must never overwrite a destination that was independently changed after Shrinkydink staged its plan; detect that condition and report it rather than guessing.
