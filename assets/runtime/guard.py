#!/usr/bin/env python3
"""Best-effort PreToolUse guard for the repository's configured ignore file.

The same JSON response shape is accepted by Claude Code and OpenAI Codex.
This is a guardrail, not a sandbox: hosted tools, direct @-imports, and some
specialized tool paths may bypass lifecycle hooks.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

RUNTIME_DIRECTORY = str(Path(__file__).resolve().parent)
if RUNTIME_DIRECTORY not in sys.path:
    sys.path.insert(0, RUNTIME_DIRECTORY)

from agentsignore import (  # noqa: E402
    PATH_DIRECTORY,
    PATH_FILE,
    AgentsIgnoreMatcher,
    Rule,
)

DEFAULT_MODE = "warn"
PATH_KEYS = {
    "file",
    "files",
    "file_path",
    "file_paths",
    "filepath",
    "filename",
    "path",
    "paths",
    "directory",
    "directories",
    "dir",
    "root",
    "roots",
    "target",
    "targets",
    "source",
    "sources",
    "destination",
    "destinations",
}
SKIP_KEYS = {
    "content",
    "old_string",
    "new_string",
    "prompt",
    "query",
    "description",
}
PATCH_PATH_RE = re.compile(
    r"^\*\*\*\s+(?:(?:Add|Update|Delete|Move to)\s+File:|Move to:)\s+(.+?)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class SearchOperation:
    scopes: tuple[str, ...]
    exclusions: tuple[str, ...]


def repo_root(payload: dict[str, Any]) -> Path:
    """Find the repository root without depending on the hook working directory."""
    installed_root = Path(__file__).resolve().parents[2]
    if (installed_root / ".git").exists() or (installed_root / ".shrinkydink.json").exists():
        return installed_root

    for value in (os.environ.get("CLAUDE_PROJECT_DIR"), payload.get("cwd"), os.getcwd()):
        if not value:
            continue
        candidate = Path(str(value)).expanduser().resolve()
        current = candidate if candidate.is_dir() else candidate.parent
        for parent in (current, *current.parents):
            if (parent / ".git").exists() or (parent / ".shrinkydink.json").exists():
                return parent
    return installed_root


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def strings_from_paths(
    value: Any, key: str = "", path_context: bool = False
) -> Iterable[str]:
    """Yield strings only when they occur in an explicitly path-bearing field."""
    if isinstance(value, str):
        if path_context or key in PATH_KEYS:
            yield value
        return

    if isinstance(value, dict):
        for child_key, child_value in value.items():
            lowered = str(child_key).lower()
            if lowered in SKIP_KEYS:
                continue
            if lowered == "command" and not path_context:
                continue
            yield from strings_from_paths(
                child_value,
                lowered,
                path_context or lowered in PATH_KEYS,
            )
        return

    if isinstance(value, (list, tuple)):
        for child in value:
            yield from strings_from_paths(child, key, path_context)


def literal_prefix(value: str) -> str:
    match = re.search(r"[*?\[]", value)
    if match:
        value = value[: match.start()]
    return value.rstrip("/")


def candidate_kind(candidate: str, root: Path, cwd: Path) -> str:
    spelling = literal_prefix(candidate.replace("\\", "/"))
    if candidate.endswith(("/", "\\")):
        return PATH_DIRECTORY
    path = Path(spelling).expanduser()
    if not path.is_absolute():
        path = cwd / path
    try:
        if path.resolve(strict=False).is_dir():
            return PATH_DIRECTORY
    except OSError:
        pass
    return PATH_FILE


def shell_segments(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except (TypeError, ValueError):
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            tokens = command.split()

    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in {";", "&", "&&", "|", "||"}:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def positional_args(
    args: list[str],
    value_options: set[str],
    pattern_options: Optional[set[str]] = None,
) -> tuple[list[str], bool]:
    positionals: list[str] = []
    pattern_from_option = False
    pattern_options = pattern_options or set()
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            positionals.extend(args[index + 1 :])
            break

        option_name = token.split("=", 1)[0]
        if option_name in pattern_options:
            pattern_from_option = True
        if option_name in value_options:
            index += 1 if "=" in token else 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        positionals.append(token)
        index += 1
    return positionals, pattern_from_option


def option_values(
    args: list[str], names: set[str], attached_short: Optional[set[str]] = None
) -> list[str]:
    """Return values for a bounded set of options without evaluating the shell."""
    values: list[str] = []
    attached_short = attached_short or set()
    index = 0
    while index < len(args):
        token = args[index]
        option_name, separator, inline_value = token.partition("=")
        if option_name in names:
            if separator:
                values.append(inline_value)
            elif index + 1 < len(args):
                values.append(args[index + 1])
                index += 1
        else:
            for short_name in attached_short:
                if token.startswith(short_name) and token != short_name:
                    values.append(token[len(short_name) :])
                    break
        index += 1
    return values


def strip_environment_assignments(segment: list[str]) -> list[str]:
    while segment and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", segment[0]):
        segment = segment[1:]
    return segment


def generic_shell_paths(tokens: Iterable[str]) -> Iterable[str]:
    for token in tokens:
        cleaned = token.strip("'\"`()[]{};,:")
        if not cleaned or cleaned.startswith("-") or "=" in cleaned[:40]:
            continue
        if cleaned.startswith(("http://", "https://", "ssh://")):
            continue
        if "/" in cleaned or "\\" in cleaned or cleaned.startswith("."):
            yield cleaned


def analyze_shell_command(command: str) -> tuple[list[str], list[SearchOperation]]:
    """Extract bounded path operands and filesystem-search scopes."""
    candidates = [path.strip() for path in PATCH_PATH_RE.findall(command)]
    operations: list[SearchOperation] = []

    rg_value_options = {
        "-A", "--after-context", "-B", "--before-context", "-C", "--context",
        "--context-separator", "--dfa-size-limit", "-E", "--encoding", "--engine",
        "-f", "--file", "-g", "--glob", "--iglob", "--max-columns",
        "--max-columns-preview", "--max-count", "--max-depth", "--max-filesize",
        "--path-separator", "--pre", "--pre-glob", "-r", "--replace", "--sort",
        "--sortr", "-t", "--type", "--type-add", "--type-clear",
    }
    rg_pattern_options = {"-e", "--regexp", "-f", "--file"}
    grep_value_options = {
        "-A", "--after-context", "-B", "--before-context", "-C", "--context",
        "-e", "--regexp", "-f", "--file", "--exclude", "--exclude-from",
        "--exclude-dir", "--include", "-m", "--max-count",
    }
    fd_value_options = {
        "-d", "--max-depth", "--min-depth", "-E", "--exclude", "-e", "--extension",
        "-g", "--glob", "--changed-before", "--changed-within", "-j", "--threads",
        "-S", "--size", "-t", "--type", "-x", "--exec", "-X", "--exec-batch",
    }
    file_command_options = {
        "cat": set(),
        "head": {"-c", "--bytes", "-n", "--lines"},
        "cp": {"-S", "--suffix", "-t", "--target-directory"},
        "rm": set(),
    }

    for original_segment in shell_segments(command):
        segment = strip_environment_assignments(original_segment)
        if not segment:
            continue
        executable = Path(segment[0]).name.lower()
        args = segment[1:]

        if executable in {"rg", "ripgrep"}:
            positionals, pattern_from_option = positional_args(
                args, rg_value_options | rg_pattern_options, rg_pattern_options
            )
            scopes = positionals if pattern_from_option else positionals[1:]
            glob_values = option_values(
                args, {"-g", "--glob", "--iglob"}, {"-g"}
            )
            exclusions = [value[1:] for value in glob_values if value.startswith("!")]
            candidates.extend(scopes)
            operations.append(SearchOperation(tuple(scopes), tuple(exclusions)))
            continue

        recursive_grep = executable == "grep" and any(
            token in {"-r", "-R", "--recursive"}
            or (
                token.startswith("-")
                and not token.startswith("--")
                and "r" in token.lower()
            )
            for token in args
        )
        if recursive_grep:
            positionals, pattern_from_option = positional_args(
                args, grep_value_options, {"-e", "--regexp", "-f", "--file"}
            )
            scopes = positionals if pattern_from_option else positionals[1:]
            exclusions = option_values(args, {"--exclude", "--exclude-dir"})
            candidates.extend(scopes)
            operations.append(SearchOperation(tuple(scopes), tuple(exclusions)))
            continue

        if executable in {"fd", "fdfind"}:
            positionals, _ = positional_args(args, fd_value_options)
            scopes = positionals[1:]
            exclusions = option_values(args, {"-E", "--exclude"}, {"-E"})
            candidates.extend(scopes)
            operations.append(SearchOperation(tuple(scopes), tuple(exclusions)))
            continue

        if executable == "find":
            scopes: list[str] = []
            for token in args:
                if token.startswith("-") or token in {"!", "("}:
                    break
                scopes.append(token)
            candidates.extend(scopes)
            operations.append(SearchOperation(tuple(scopes), ()))
            continue

        recursive_ls = executable == "ls" and any(
            token == "--recursive"
            or (token.startswith("-") and not token.startswith("--") and "R" in token)
            for token in args
        )
        if recursive_ls:
            scopes, _ = positional_args(args, set())
            candidates.extend(scopes)
            operations.append(SearchOperation(tuple(scopes), ()))
            continue

        if executable in file_command_options:
            positionals, _ = positional_args(args, file_command_options[executable])
            candidates.extend(positionals)
            if executable == "cp":
                candidates.extend(
                    option_values(args, {"-t", "--target-directory"}, {"-t"})
                )
            continue

        candidates.extend(generic_shell_paths(args))

    return candidates, operations


def target_is_repo_root(value: str, root: Path, cwd: Path) -> bool:
    candidate = literal_prefix(value.strip().replace("\\", "/"))
    if not candidate or candidate in {".", "./"}:
        return True
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = cwd / path
    try:
        return path.resolve(strict=False) == root.resolve()
    except OSError:
        return False


def operation_may_traverse_ignored(
    operation: SearchOperation,
    matcher: AgentsIgnoreMatcher,
    root: Path,
    cwd: Path,
) -> bool:
    if not matcher.active_ignore_rules or matcher.exclusions_cover(operation.exclusions):
        return False
    if not operation.scopes:
        return True

    for scope in operation.scopes:
        if target_is_repo_root(scope, root, cwd):
            return True
        normalized = matcher.normalize(
            literal_prefix(scope.replace("\\", "/")), root, cwd, PATH_DIRECTORY
        )
        if normalized.state != "inside":
            # A scope outside this repository cannot traverse its ignored paths.
            continue
        if matcher.may_ignore_under(normalized.relative or ""):
            return True
    return False


def direct_search_operation(tool_name: str, tool_input: Any) -> Optional[SearchOperation]:
    if not isinstance(tool_input, dict):
        return None
    normalized_name = tool_name.lower()
    explicit_path = tool_input.get("path") or tool_input.get("directory")
    scopes: list[str] = []
    if isinstance(explicit_path, str) and explicit_path:
        scopes.append(explicit_path)

    if normalized_name == "grep":
        glob_value = tool_input.get("glob")
        exclusions: list[str] = []
        if isinstance(glob_value, str) and glob_value.startswith("!"):
            exclusions.append(glob_value[1:])
        elif not scopes and isinstance(glob_value, str) and "/" in glob_value:
            prefix = literal_prefix(glob_value)
            if prefix:
                scopes.append(prefix)
        return SearchOperation(tuple(scopes), tuple(exclusions))

    if normalized_name == "glob":
        if not scopes:
            pattern = tool_input.get("pattern") or tool_input.get("glob")
            if isinstance(pattern, str):
                prefix = literal_prefix(pattern)
                if prefix:
                    scopes.append(prefix)
        return SearchOperation(tuple(scopes), ())
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
    except (json.JSONDecodeError, OSError):
        return 0

    root = repo_root(payload)
    config = load_json(root / ".shrinkydink.json")
    mode = str(config.get("ignore_mode", DEFAULT_MODE)).lower()
    if mode not in {"warn", "deny", "off"}:
        mode = DEFAULT_MODE
    if mode == "off":
        return 0

    ignore_name = str(config.get("agentsignore", ".agentsignore"))
    ignore_relative = Path(ignore_name)
    if ignore_relative.is_absolute() or ".." in ignore_relative.parts:
        ignore_relative = Path(".agentsignore")
    ignore_path = root / ignore_relative
    matcher = AgentsIgnoreMatcher.from_file(ignore_path)
    effective_rules = list(matcher.active_ignore_rules)
    if not effective_rules:
        return 0

    cwd_value = payload.get("cwd") or os.getcwd()
    try:
        cwd = Path(str(cwd_value)).expanduser().resolve()
    except OSError:
        cwd = root

    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input", {})
    candidates = list(strings_from_paths(tool_input))
    search_operations: list[SearchOperation] = []
    command = ""
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        command = tool_input["command"]
        shell_candidates, shell_operations = analyze_shell_command(command)
        candidates.extend(shell_candidates)
        search_operations.extend(shell_operations)

    # Glob patterns sometimes name an ignored directory directly. A Grep
    # search pattern is content, not a path, so only its optional glob filter
    # is considered here.
    if isinstance(tool_input, dict):
        if tool_name.lower() == "glob":
            value = tool_input.get("pattern") or tool_input.get("glob")
            if isinstance(value, str):
                candidates.append(value)
        direct_operation = direct_search_operation(tool_name, tool_input)
        if direct_operation is not None:
            search_operations.append(direct_operation)

    matches: list[tuple[str, Rule]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        candidate_text = str(candidate)
        kind = candidate_kind(candidate_text, root, cwd)
        normalized = matcher.normalize(
            literal_prefix(candidate_text.replace("\\", "/")), root, cwd, kind
        )
        if normalized.state != "inside" or not normalized.relative:
            continue
        key = (normalized.relative, kind)
        if key in seen:
            continue
        seen.add(key)
        result = matcher.match(normalized.relative, kind)
        if result.ignored and result.rule:
            matches.append((normalized.relative, result.rule))

    broad_search = any(
        operation_may_traverse_ignored(operation, matcher, root, cwd)
        for operation in search_operations
    )
    if not matches and not broad_search:
        return 0

    if matches:
        details = ", ".join(
            f"{path} (rule: {rule.raw})" for path, rule in matches[:4]
        )
        if len(matches) > 4:
            details += f", plus {len(matches) - 4} more"
        if mode == "deny":
            guidance = (
                "Repository policy is deny mode. Change `.shrinkydink.json` to `warn` "
                "before making an intentional, documented exception."
            )
        else:
            guidance = (
                "Use the narrowest necessary access. In warn mode, proceed only for an "
                "explicit user request or an indispensable, documented exception."
            )
        message = (
            f"Shrinkydink: this tool call touches paths matched by {ignore_name}: "
            f"{details}. {guidance} Never reveal secret values from ignored files."
        )
    else:
        details = ", ".join(rule.raw for rule in effective_rules[:4])
        if len(effective_rules) > 4:
            details += f", plus {len(effective_rules) - 4} more"
        message = (
            f"Shrinkydink: this broad operation may traverse paths in {ignore_name} "
            f"matched by rules: {details}. Use a narrower target or explicitly exclude "
            "every active rule before ingesting results. Never reveal secret values from "
            "ignored files."
        )

    output: dict[str, Any] = {"systemMessage": message}
    hook_output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "additionalContext": message,
    }
    if mode == "deny" and (matches or broad_search):
        hook_output["permissionDecision"] = "deny"
        hook_output["permissionDecisionReason"] = message
    output["hookSpecificOutput"] = hook_output
    json.dump(output, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
