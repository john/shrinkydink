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

DEFAULT_MODE = "warn"
PATH_KEYS = {
    "file",
    "file_path",
    "filepath",
    "filename",
    "path",
    "directory",
    "dir",
    "root",
    "target",
    "source",
    "destination",
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
    r"^\*\*\*\s+(?:Add|Update|Delete|Move to)\s+File:\s+(.+?)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Rule:
    raw: str
    pattern: str
    negated: bool
    directory_only: bool
    regex: re.Pattern[str]


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


def translate_gitignore(pattern: str, directory_only: bool) -> re.Pattern[str]:
    """Translate the practical subset of gitignore syntax used by shrinkydink."""
    anchored = pattern.startswith("/")
    if anchored:
        pattern = pattern[1:]

    has_slash = "/" in pattern
    i = 0
    chunks: list[str] = []
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    chunks.append("(?:.*/)?")
                    i += 1
                else:
                    chunks.append(".*")
                continue
            chunks.append("[^/]*")
        elif char == "?":
            chunks.append("[^/]")
        elif char == "[":
            end = pattern.find("]", i + 1)
            if end != -1:
                content = pattern[i + 1 : end]
                if content.startswith("!"):
                    content = "^" + content[1:]
                chunks.append("[" + content.replace("\\", "\\\\") + "]")
                i = end
            else:
                chunks.append(r"\[")
        else:
            chunks.append(re.escape(char))
        i += 1

    body = "".join(chunks)
    if anchored or has_slash:
        prefix = "^"
    else:
        prefix = r"^(?:.*/)?"

    # Treat a matching path as a possible directory and include descendants.
    # This slightly over-approximates Git for impossible file/child paths, which
    # is safer for a context-ingestion guard.
    suffix = r"(?:/.*)?$"
    return re.compile(prefix + body + suffix)


def parse_rules(path: Path) -> list[Rule]:
    rules: list[Rule] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return rules

    for original in lines:
        line = original.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        elif line.startswith(r"\#"):
            line = line[1:]
        if not line:
            continue
        directory_only = line.endswith("/")
        if directory_only:
            line = line[:-1]
        try:
            regex = translate_gitignore(line, directory_only)
        except re.error:
            continue
        rules.append(
            Rule(
                raw=original,
                pattern=line,
                negated=negated,
                directory_only=directory_only,
                regex=regex,
            )
        )
    return rules


def match_rule(relative_path: str, rules: Iterable[Rule]) -> Optional[Rule]:
    normalized = relative_path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    matched: Optional[Rule] = None
    ignored = False
    for rule in rules:
        if rule.regex.match(normalized):
            ignored = not rule.negated
            matched = rule if ignored else None
    return matched if ignored else None


def strings_from_paths(value: Any, key: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            lowered = str(child_key).lower()
            if lowered in SKIP_KEYS:
                continue
            if lowered in PATH_KEYS and isinstance(child_value, str):
                yield child_value
            elif lowered not in {"command"}:
                yield from strings_from_paths(child_value, lowered)
    elif isinstance(value, list):
        for child in value:
            yield from strings_from_paths(child, key)


def shell_path_candidates(command: str) -> Iterable[str]:
    for patch_path in PATCH_PATH_RE.findall(command):
        yield patch_path.strip()

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()

    for token in tokens:
        cleaned = token.strip("'\"`()[]{};,:")
        if not cleaned or cleaned.startswith("-") or "=" in cleaned[:40]:
            continue
        if cleaned.startswith(("http://", "https://", "ssh://")):
            continue
        if "/" in cleaned or "\\" in cleaned or cleaned.startswith("."):
            yield cleaned


def literal_prefix(value: str) -> str:
    match = re.search(r"[*?\[]", value)
    if match:
        value = value[: match.start()]
    return value.rstrip("/")


def to_relative(candidate: str, root: Path, cwd: Path) -> Optional[str]:
    candidate = candidate.strip().replace("\\", "/")
    if not candidate or candidate in {".", "./", root.as_posix()}:
        return None
    candidate = literal_prefix(candidate)
    if not candidate:
        return None

    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = cwd / path
    try:
        resolved = path.resolve(strict=False)
        return resolved.relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


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


def repo_wide_shell_search(command: str, root: Path, cwd: Path) -> bool:
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

    for segment in shell_segments(command):
        while segment and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", segment[0]):
            segment = segment[1:]
        if not segment:
            continue
        executable = Path(segment[0]).name.lower()
        args = segment[1:]

        if executable in {"rg", "ripgrep"}:
            positionals, pattern_from_option = positional_args(
                args, rg_value_options | rg_pattern_options, rg_pattern_options
            )
            targets = positionals if pattern_from_option else positionals[1:]
        elif executable == "grep" and any(
            token in {"-r", "-R", "--recursive"}
            or (token.startswith("-") and not token.startswith("--") and "r" in token.lower())
            for token in args
        ):
            positionals, pattern_from_option = positional_args(
                args, grep_value_options, {"-e", "--regexp", "-f", "--file"}
            )
            targets = positionals if pattern_from_option else positionals[1:]
        elif executable in {"fd", "fdfind"}:
            positionals, _ = positional_args(args, fd_value_options)
            targets = positionals[1:]
        elif executable == "find":
            targets = []
            for token in args:
                if token.startswith("-") or token in {"!", "("}:
                    break
                targets.append(token)
            targets = targets[:1]
        elif executable == "ls" and any(
            token == "--recursive"
            or (token.startswith("-") and not token.startswith("--") and "R" in token)
            for token in args
        ):
            targets, _ = positional_args(args, set())
        else:
            continue

        if not targets or any(target_is_repo_root(target, root, cwd) for target in targets):
            return True
    return False


def repo_wide_direct_search(
    tool_name: str, tool_input: Any, root: Path, cwd: Path
) -> bool:
    if not isinstance(tool_input, dict):
        return False
    normalized_name = tool_name.lower()
    explicit_path = tool_input.get("path") or tool_input.get("directory")
    if isinstance(explicit_path, str) and explicit_path:
        return target_is_repo_root(explicit_path, root, cwd)

    if normalized_name == "grep":
        return True
    if normalized_name == "glob":
        pattern = tool_input.get("pattern") or tool_input.get("glob")
        if not isinstance(pattern, str):
            return True
        prefix = literal_prefix(pattern)
        return not prefix or target_is_repo_root(prefix, root, cwd)
    return False


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
    rules = parse_rules(ignore_path)
    if not rules:
        return 0

    cwd_value = payload.get("cwd") or os.getcwd()
    try:
        cwd = Path(str(cwd_value)).expanduser().resolve()
    except OSError:
        cwd = root

    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input", {})
    candidates = list(strings_from_paths(tool_input))
    command = ""
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        command = tool_input["command"]
        candidates.extend(shell_path_candidates(command))

    # Glob patterns sometimes name an ignored directory directly. A Grep
    # search pattern is content, not a path, so only its optional glob filter
    # is considered here.
    if isinstance(tool_input, dict):
        keys = ("pattern", "glob") if tool_name.lower() == "glob" else ("glob",)
        for key in keys:
            value = tool_input.get(key)
            if isinstance(value, str) and "/" in value:
                candidates.append(value)

    matches: list[tuple[str, Rule]] = []
    seen: set[str] = set()
    for candidate in candidates:
        relative = to_relative(str(candidate), root, cwd)
        if not relative or relative in seen:
            continue
        seen.add(relative)
        rule = match_rule(relative, rules)
        if rule:
            matches.append((relative, rule))

    broad_search = bool(command and repo_wide_shell_search(command, root, cwd))
    broad_search = broad_search or repo_wide_direct_search(tool_name, tool_input, root, cwd)
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
        message = (
            f"Shrinkydink: this broad search may traverse paths in {ignore_name}. "
            "Add explicit exclusions or use a narrower target before ingesting results."
        )

    output: dict[str, Any] = {"systemMessage": message}
    hook_output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "additionalContext": message,
    }
    if mode == "deny" and matches:
        hook_output["permissionDecision"] = "deny"
        hook_output["permissionDecisionReason"] = message
    output["hookSpecificOutput"] = hook_output
    json.dump(output, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
