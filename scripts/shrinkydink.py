#!/usr/bin/env python3
"""Audit or configure a repository for compact, cross-agent coding context.

No third-party packages are required. The script is intentionally conservative:
it preserves user content outside managed blocks, merges JSON structurally, and
reports conflicts rather than replacing configuration it cannot understand.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and older
    tomllib = None  # type: ignore[assignment]

VERSION = 1
DEFAULT_CONTEXT_WARNING_PERCENT = 70
DEFAULT_IGNORE_MODE = "warn"
DEFAULT_LARGE_FILE_WARNING_KB = 256
TEXT_START = "# shrinkydink:start"
TEXT_END = "# shrinkydink:end"
MD_START = "<!-- shrinkydink:start -->"
MD_END = "<!-- shrinkydink:end -->"
CODEX_HOOK_START = "# shrinkydink:hooks:start"
CODEX_HOOK_END = "# shrinkydink:hooks:end"
CODEX_STATUS_MARKER = "# shrinkydink:context-status"


@dataclass
class Change:
    path: str
    status: str
    note: str
    old: Optional[str] = None
    new: Optional[str] = None
    mode: Optional[int] = None

    @property
    def changed(self) -> bool:
        return self.status in {"create", "update"}


@dataclass
class WarningItem:
    kind: str
    message: str


@dataclass
class StagedChange:
    change: Change
    path: Path
    temp_path: Path
    prior_bytes: Optional[bytes]
    prior_mode: Optional[int]
    written_bytes: bytes
    written_hash: str


@dataclass
class ApplyResult:
    warnings: list[WarningItem]
    completed: bool
    restored: list[str]
    rollback_skipped: list[str]


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def resolve_repo(path: str) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError(f"Repository path is not a directory: {candidate}")
    result = run_git(candidate, "rev-parse", "--show-toplevel")
    if result.returncode == 0 and result.stdout.strip():
        candidate = Path(result.stdout.strip()).resolve()
    if candidate == Path.home().resolve():
        raise ValueError("Refusing to manage the current user's home directory")
    if candidate.parent == candidate:
        raise ValueError("Refusing to manage a filesystem root")
    return candidate


def path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_managed_destination(
    root: Path, relative: Path
) -> tuple[Optional[Path], Optional[str]]:
    """Validate one repository-relative destination without writing to it."""
    if relative.is_absolute() or ".." in relative.parts:
        return None, f"Managed destination must stay within the repository: {relative}"

    root_real = root.resolve()
    destination = root / relative
    current = root
    for part in relative.parts:
        if part in {"", "."}:
            continue
        current = current / part
        try:
            is_link = current.is_symlink()
            exists = current.exists()
            if is_link or exists:
                resolved = current.resolve(strict=False)
                if not path_within(resolved, root_real):
                    kind = "symbolic link component" if is_link else "path component"
                    shown = current.relative_to(root).as_posix()
                    return (
                        None,
                        f"Unsafe managed destination `{relative.as_posix()}`: {kind} "
                        f"`{shown}` resolves outside the repository",
                    )
            if not exists and not is_link:
                break
        except OSError as exc:
            shown = current.relative_to(root).as_posix()
            return None, f"Cannot validate managed destination component `{shown}`: {exc}"

    try:
        parent_real = destination.parent.resolve(strict=False)
    except OSError as exc:
        return None, f"Cannot validate managed destination `{relative.as_posix()}`: {exc}"
    if not path_within(parent_real, root_real):
        return (
            None,
            f"Unsafe managed destination `{relative.as_posix()}`: its parent resolves "
            "outside the repository",
        )
    return destination, None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def newline_style(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def merge_managed_block(
    existing: str,
    body: str,
    start: str = TEXT_START,
    end: str = TEXT_END,
    placement: str = "append",
) -> str:
    if placement not in {"append", "prepend"}:
        raise ValueError(f"Unsupported managed-block placement: {placement}")
    newline = newline_style(existing)
    normalized = normalize_newlines(existing)
    block = f"{start}\n{body.rstrip()}\n{end}"

    start_count = normalized.count(start)
    end_count = normalized.count(end)
    if start_count != end_count:
        raise ValueError(f"Found only one managed marker ({start!r}, {end!r})")
    if start_count > 1:
        raise ValueError("Found multiple managed blocks")

    start_index = normalized.find(start)
    end_index = normalized.find(end)
    if start_index != -1:
        if end_index < start_index:
            raise ValueError("Managed block end marker appears before start marker")
        end_index += len(end)
        merged = normalized[:start_index] + block + normalized[end_index:]
    else:
        if placement == "prepend":
            merged = f"{block}\n\n{normalized}" if normalized else f"{block}\n"
        else:
            prefix = normalized.rstrip()
            merged = f"{prefix}\n\n{block}\n" if prefix else f"{block}\n"

    merged = merged.rstrip("\n") + "\n"
    return merged.replace("\n", newline)


def json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=False) + "\n"


def load_json_object(path: Path) -> tuple[dict[str, Any], Optional[str]]:
    if not path.exists():
        return {}, None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return {}, f"File is not valid UTF-8: {exc}"
    except OSError as exc:
        return {}, f"Cannot read file: {exc}"
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
    if not isinstance(value, dict):
        return {}, "Top-level JSON value must be an object"
    return value, None


def classify_change(path: Path, new: str, note: str = "") -> Change:
    if path.is_symlink():
        try:
            old = read_text(path)
        except (OSError, UnicodeDecodeError):
            old = None
        if old == new:
            return Change(path=str(path), status="ok", note=f"{note}; symlink unchanged", old=old, new=new)
        return Change(
            path=str(path),
            status="conflict",
            note=f"{note}; refusing to replace a symbolic link",
            old=old,
            new=None,
        )
    if path.exists() and not path.is_file():
        return Change(
            path=str(path),
            status="conflict",
            note=f"{note}; expected a regular file",
            old=None,
            new=None,
        )
    if not path.exists():
        return Change(path=str(path), status="create", note=note, old="", new=new)
    old = read_text(path)
    if old == new:
        return Change(path=str(path), status="ok", note=note, old=old, new=new)
    return Change(path=str(path), status="update", note=note, old=old, new=new)


def conflict(path: Path, note: str) -> Change:
    try:
        old = read_text(path)
    except (OSError, UnicodeDecodeError):
        old = None
    return Change(path=str(path), status="conflict", note=note, old=old, new=None)


def unique(lines: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            result.append(line)
    return result


def detect_ecosystems(root: Path, max_depth: int = 3) -> set[str]:
    markers = {
        "node": {"package.json", "pnpm-workspace.yaml", "yarn.lock"},
        "python": {"pyproject.toml", "requirements.txt", "Pipfile", "setup.py", "tox.ini"},
        "rust": {"Cargo.toml"},
        "go": {"go.mod"},
        "java": {"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle"},
        "dotnet": {"global.json"},
        "ruby": {"Gemfile"},
        "terraform": {".terraform.lock.hcl"},
        "swift": {"Package.swift"},
    }
    suffix_markers = {"dotnet": {".sln", ".csproj", ".fsproj"}, "terraform": {".tf"}}
    detected: set[str] = set()
    pruned = {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "vendor",
        "dist",
        "build",
        "target",
        ".next",
        ".cache",
    }

    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            continue
        dirs[:] = [d for d in dirs if d not in pruned and depth < max_depth]
        file_set = set(files)
        for ecosystem, names in markers.items():
            if names & file_set:
                detected.add(ecosystem)
        for filename in files:
            suffix = Path(filename).suffix
            for ecosystem, suffixes in suffix_markers.items():
                if suffix in suffixes:
                    detected.add(ecosystem)
        if depth >= max_depth:
            dirs[:] = []
    return detected


def gitignore_body(ecosystems: set[str]) -> str:
    groups: list[tuple[str, list[str]]] = [
        (
            "Local agent and personal configuration",
            [
                ".claude/settings.local.json",
                "CLAUDE.local.md",
                ".codex/*.local.*",
                ".agent-tools/shrinkydink/__pycache__/",
            ],
        ),
        (
            "Secrets and local environment files",
            [
                ".env",
                ".env.*",
                "!.env.example",
                "!.env.sample",
                "!.env.template",
                "*.pem",
                "*.p12",
                "*.pfx",
            ],
        ),
        (
            "Operating-system and editor residue",
            [".DS_Store", "Thumbs.db", "*.swp", "*.swo", "*~"],
        ),
        ("Logs and temporary output", ["*.log", "tmp/", "temp/"]),
    ]

    ecosystem_patterns: dict[str, tuple[str, list[str]]] = {
        "node": (
            "Node.js",
            [
                "node_modules/",
                ".npm/",
                ".pnpm-store/",
                ".yarn/cache/",
                ".yarn/unplugged/",
                "dist/",
                "build/",
                "coverage/",
                ".next/",
                ".nuxt/",
                ".svelte-kit/",
                ".turbo/",
            ],
        ),
        "python": (
            "Python",
            [
                "__pycache__/",
                "*.py[cod]",
                ".venv/",
                "venv/",
                ".pytest_cache/",
                ".mypy_cache/",
                ".ruff_cache/",
                ".tox/",
                ".nox/",
                ".coverage",
                "htmlcov/",
                "*.egg-info/",
                "dist/",
                "build/",
            ],
        ),
        "rust": ("Rust", ["/target/"]),
        "go": ("Go", ["/bin/", "*.test", "coverage.out"]),
        "java": ("Java, Maven, and Gradle", [".gradle/", "target/", "build/", "*.class"]),
        "dotnet": (".NET", ["bin/", "obj/", ".vs/", "*.user", "*.suo"]),
        "ruby": ("Ruby", [".bundle/", "vendor/bundle/", "log/", "tmp/"]),
        "terraform": (
            "Terraform",
            [".terraform/", "*.tfstate", "*.tfstate.*", "crash.log", "crash.*.log"],
        ),
        "swift": ("Swift", [".build/", "DerivedData/"]),
    }
    for ecosystem in sorted(ecosystems):
        if ecosystem in ecosystem_patterns:
            groups.append(ecosystem_patterns[ecosystem])

    rendered: list[str] = [
        "# Managed by /shrinkydink. Keep project-specific rules outside this block."
    ]
    for title, patterns in groups:
        rendered.extend(["", f"# {title}", *unique(patterns)])
    return "\n".join(rendered).strip()


def gitattributes_body() -> str:
    return """# Managed by /shrinkydink. Keep project-specific rules outside this block.
# Normalize text while preserving platform-specific script endings.
* text=auto
*.sh text eol=lf
*.bash text eol=lf
*.zsh text eol=lf
*.py text eol=lf
*.js text eol=lf
*.ts text eol=lf
*.json text eol=lf
*.yaml text eol=lf
*.yml text eol=lf
*.md text eol=lf
*.bat text eol=crlf
*.cmd text eol=crlf

# Avoid textual diffs and merges for common binary formats.
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.webp binary
*.ico binary
*.pdf binary
*.zip binary
*.gz binary
*.7z binary
*.woff binary
*.woff2 binary
*.ttf binary
*.otf binary"""


def agentsignore_body(ecosystems: set[str], ignore_name: str = ".agentsignore") -> str:
    managed_line = "# Managed by /shrinkydink. Add repo-specific rules outside this block."
    if ignore_name != ".agentsignore":
        managed_line = (
            f"# Managed by /shrinkydink at {ignore_name}. "
            "Add repo-specific rules outside this block."
        )
    patterns = [
        managed_line,
        "# Syntax is the practical gitignore subset documented by this skill.",
        "",
        "# Version-control internals and agent-local state",
        ".git/",
        ".claude/settings.local.json",
        "CLAUDE.local.md",
        ".agent-tools/shrinkydink/__pycache__/",
        "",
        "# Secrets: do not ingest these into model context",
        ".env",
        ".env.*",
        "!.env.example",
        "!.env.sample",
        "!.env.template",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "",
        "# Dependencies, caches, build products, and coverage",
        "node_modules/",
        "vendor/",
        ".venv/",
        "venv/",
        "__pycache__/",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
        ".tox/",
        ".nox/",
        ".gradle/",
        ".cache/",
        ".turbo/",
        ".next/",
        ".nuxt/",
        ".svelte-kit/",
        "target/",
        "dist/",
        "build/",
        "out/",
        "coverage/",
        "htmlcov/",
        "tmp/",
        "temp/",
        "*.log",
        "",
        "# Generated bundles and source maps",
        "*.min.js",
        "*.min.css",
        "*.map",
        "",
        "# Binary databases, archives, and compiled artifacts",
        "*.db",
        "*.sqlite",
        "*.sqlite3",
        "*.zip",
        "*.tar",
        "*.tar.gz",
        "*.tgz",
        "*.7z",
        "*.rar",
        "*.jar",
        "*.war",
        "*.class",
        "*.o",
        "*.so",
        "*.dylib",
        "*.dll",
        "*.exe",
        "*.bin",
    ]
    if "terraform" in ecosystems:
        patterns.extend(["", "# Terraform local state", ".terraform/", "*.tfstate", "*.tfstate.*"])
    return "\n".join(patterns).strip()


def agents_md_body(threshold: int, ignore_name: str = ".agentsignore") -> str:
    remaining = 100 - threshold
    return f"""## Repository context hygiene

- Treat `{ignore_name}` as an agent-specific exclusion list using gitignore-style patterns. Do not read, search, summarize, index, or attach matching content unless the user explicitly requests it or it is indispensable to the task.
- In `warn` mode, an explicit user request may justify a documented exception. In `deny` mode, stop and ask the user to change `.shrinkydink.json` to `warn` before accessing a matched path.
- When an exception is necessary, explain why and inspect the narrowest possible file, range, or command output. Never reveal secret values from ignored files.
- Prefer targeted symbol search, path-scoped search, and bounded reads over recursive repository ingestion. Summarize discoveries with exact file paths and symbols, then discard bulky raw output.
- Do not load generated files, dependency trees, caches, archives, databases, source maps, or minified bundles when source files or targeted queries are available.
- When the interface reports context usage at or above {threshold}% ({remaining}% remaining), warn the user and recommend checkpointing work and starting a new session at the next clean boundary.
- Before a new session, leave a compact handoff containing: objective, key decisions, changed files, verification performed, unresolved issues, and the next command or action.
- Treat `{ignore_name}` hooks as guardrails, not proof of isolation. Follow these rules even when a tool path bypasses hooks."""


def claude_md_body(ignore_name: str = ".agentsignore") -> str:
    return """@AGENTS.md

## Claude Code integration

The shared repository instructions are imported from `AGENTS.md`. Local `{ignore_name}` guard and context-status hooks are configured in `.claude/settings.local.json` when that file can be merged safely. Treat hook warnings as instructions to narrow the operation; an explicit user request may justify a documented exception when `ignore_mode` is `warn`.""".format(ignore_name=ignore_name)


def desired_config(existing: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    result = dict(existing)
    result.setdefault("version", VERSION)
    result.setdefault("context_warning_percent", DEFAULT_CONTEXT_WARNING_PERCENT)
    result.setdefault("ignore_mode", DEFAULT_IGNORE_MODE)
    result.setdefault("large_file_warning_kb", DEFAULT_LARGE_FILE_WARNING_KB)
    result.setdefault("agentsignore", ".agentsignore")
    if args.context_warning_percent is not None:
        result["context_warning_percent"] = args.context_warning_percent
    if args.ignore_mode is not None:
        result["ignore_mode"] = args.ignore_mode
    if args.large_file_warning_kb is not None:
        result["large_file_warning_kb"] = args.large_file_warning_kb
    result["version"] = VERSION
    return result


def validate_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    threshold = config.get("context_warning_percent")
    if isinstance(threshold, bool) or not isinstance(threshold, int) or not 1 <= threshold <= 99:
        errors.append("`context_warning_percent` must be an integer from 1 to 99")

    mode = config.get("ignore_mode")
    if mode not in {"warn", "deny", "off"}:
        errors.append("`ignore_mode` must be `warn`, `deny`, or `off`")

    large_file_kb = config.get("large_file_warning_kb")
    if (
        isinstance(large_file_kb, bool)
        or not isinstance(large_file_kb, int)
        or large_file_kb < 1
    ):
        errors.append("`large_file_warning_kb` must be a positive integer")

    ignore_name = config.get("agentsignore")
    if not isinstance(ignore_name, str) or not ignore_name.strip():
        errors.append("`agentsignore` must be a non-empty repository-relative path")
    else:
        ignore_path = Path(ignore_name)
        if ignore_path.is_absolute() or ".." in ignore_path.parts:
            errors.append("`agentsignore` must stay within the repository")

    return errors


def append_hook(
    settings: dict[str, Any], event: str, matcher: str, handler: dict[str, Any], needle: str
) -> Optional[str]:
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return "Existing `hooks` value is not an object"
    entries = hooks.setdefault(event, [])
    if not isinstance(entries, list):
        return f"Existing `hooks.{event}` value is not an array"

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        handlers = entry.get("hooks", [])
        if not isinstance(handlers, list):
            continue
        for current in handlers:
            if isinstance(current, dict) and needle in str(current.get("command", "")):
                return None
    entries.append({"matcher": matcher, "hooks": [handler]})
    return None


def plan_claude_settings(path: Path) -> tuple[Change, list[WarningItem]]:
    settings, error = load_json_object(path)
    warnings: list[WarningItem] = []
    if error:
        return conflict(path, f"Cannot merge Claude settings safely: {error}"), warnings

    settings.setdefault("$schema", "https://json.schemastore.org/claude-code-settings.json")
    if "respectGitignore" not in settings:
        settings["respectGitignore"] = True
    elif settings.get("respectGitignore") is False:
        warnings.append(
            WarningItem(
                "claude",
                "`.claude/settings.local.json` explicitly disables `respectGitignore`; preserved rather than overridden.",
            )
        )

    handler = {
        "type": "command",
        "command": 'python3 "${CLAUDE_PROJECT_DIR}/.agent-tools/shrinkydink/guard.py"',
        "timeout": 5,
        "statusMessage": "Checking .agentsignore",
    }
    error = append_hook(
        settings,
        "PreToolUse",
        "^(Read|Glob|Grep|Edit|Write|Bash)$",
        handler,
        ".agent-tools/shrinkydink/guard.py",
    )
    if error:
        return conflict(path, f"Cannot merge Claude hooks safely: {error}"), warnings

    desired_status = {
        "type": "command",
        "command": 'python3 "${CLAUDE_PROJECT_DIR}/.agent-tools/shrinkydink/claude_status.py"',
        "padding": 0,
    }
    current_status = settings.get("statusLine")
    if current_status is None:
        settings["statusLine"] = desired_status
    elif "shrinkydink/claude_status.py" not in json.dumps(current_status, sort_keys=True):
        warnings.append(
            WarningItem(
                "claude",
                "An existing Claude `statusLine` was preserved. Merge the shrinkydink status script manually to get the exact threshold warning.",
            )
        )

    return classify_change(path, json_text(settings), "Merged Claude local settings"), warnings


def plan_codex_hooks_json(path: Path) -> Change:
    settings, error = load_json_object(path)
    if error:
        return conflict(path, f"Cannot merge Codex hooks safely: {error}")
    settings.setdefault("description", "Repository context guardrails managed by /shrinkydink")

    guard_handler = {
        "type": "command",
        "command": 'python3 "$(git rev-parse --show-toplevel)/.agent-tools/shrinkydink/guard.py"',
        "commandWindows": 'py -3 ".agent-tools\\shrinkydink\\guard.py"',
        "timeout": 5,
        "statusMessage": "Checking .agentsignore",
    }
    error = append_hook(
        settings,
        "PreToolUse",
        "^(Bash|apply_patch|Read|Glob|Grep|Edit|Write)$",
        guard_handler,
        ".agent-tools/shrinkydink/guard.py",
    )
    if error:
        return conflict(path, f"Cannot merge Codex PreToolUse hook safely: {error}")

    compact_handler = {
        "type": "command",
        "command": 'python3 "$(git rev-parse --show-toplevel)/.agent-tools/shrinkydink/codex_precompact.py"',
        "commandWindows": 'py -3 ".agent-tools\\shrinkydink\\codex_precompact.py"',
        "timeout": 5,
        "statusMessage": "Checkpointing context",
    }
    error = append_hook(
        settings,
        "PreCompact",
        "^(auto|manual)$",
        compact_handler,
        ".agent-tools/shrinkydink/codex_precompact.py",
    )
    if error:
        return conflict(path, f"Cannot merge Codex PreCompact hook safely: {error}")

    return classify_change(path, json_text(settings), "Merged Codex lifecycle hooks")


def codex_inline_hook_body() -> str:
    return """# Managed by /shrinkydink because this config already contains inline hooks.
[[hooks.PreToolUse]]
matcher = "^(Bash|apply_patch|Read|Glob|Grep|Edit|Write)$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = 'python3 "$(git rev-parse --show-toplevel)/.agent-tools/shrinkydink/guard.py"'
command_windows = 'py -3 ".agent-tools\\shrinkydink\\guard.py"'
timeout = 5
statusMessage = "Checking .agentsignore"

[[hooks.PreCompact]]
matcher = "^(auto|manual)$"

[[hooks.PreCompact.hooks]]
type = "command"
command = 'python3 "$(git rev-parse --show-toplevel)/.agent-tools/shrinkydink/codex_precompact.py"'
command_windows = 'py -3 ".agent-tools\\shrinkydink\\codex_precompact.py"'
timeout = 5
statusMessage = "Checkpointing context"
"""


def ensure_codex_status_line(existing: str) -> tuple[str, Optional[str]]:
    normalized = normalize_newlines(existing)
    desired = 'status_line = ["model-with-reasoning", "context-remaining", "current-dir"]'

    # Refresh our own managed line if present.
    marker_index = normalized.find(CODEX_STATUS_MARKER)
    if marker_index != -1:
        next_newline = normalized.find("\n", marker_index)
        if next_newline == -1:
            next_newline = len(normalized)
        line_end = normalized.find("\n", next_newline + 1)
        if line_end == -1:
            line_end = len(normalized)
        replacement = f"{CODEX_STATUS_MARKER}\n{desired}"
        normalized = normalized[:marker_index] + replacement + normalized[line_end:]
        return normalized.rstrip() + "\n", None

    section_match = re.search(r"(?m)^\s*\[tui\]\s*(?:#.*)?$", normalized)
    active_status = re.search(r"(?m)^\s*status_line\s*=\s*(.+)$", normalized)
    if active_status:
        if "context-remaining" in active_status.group(1):
            return normalized.rstrip() + "\n", None
        return (
            normalized.rstrip() + "\n",
            "Existing Codex `tui.status_line` omits `context-remaining`; preserved rather than overridden.",
        )

    if section_match:
        insert_at = normalized.find("\n", section_match.end())
        if insert_at == -1:
            insert_at = len(normalized)
            suffix = ""
        else:
            insert_at += 1
            suffix = normalized[insert_at:]
        prefix = normalized[:insert_at]
        addition = f"{CODEX_STATUS_MARKER}\n{desired}\n"
        normalized = prefix + addition + suffix
    else:
        prefix = normalized.rstrip()
        addition = f"[tui]\n{CODEX_STATUS_MARKER}\n{desired}"
        normalized = f"{prefix}\n\n{addition}\n" if prefix else f"{addition}\n"
    return normalized.rstrip() + "\n", None


def plan_codex_config(path: Path, use_inline_hooks: bool) -> tuple[Change, list[WarningItem]]:
    existing = read_text(path)
    warnings: list[WarningItem] = []
    if existing and tomllib is not None:
        try:
            tomllib.loads(existing)
        except tomllib.TOMLDecodeError as exc:
            return conflict(path, f"Cannot merge invalid Codex TOML safely: {exc}"), warnings
    elif existing and tomllib is None:
        warnings.append(
            WarningItem(
                "codex",
                "Python 3.11+ is required to validate existing Codex TOML; proceeding conservatively without syntax validation.",
            )
        )

    updated, status_warning = ensure_codex_status_line(existing)
    if status_warning:
        warnings.append(WarningItem("codex", status_warning))

    if use_inline_hooks:
        try:
            updated = merge_managed_block(
                updated,
                codex_inline_hook_body(),
                CODEX_HOOK_START,
                CODEX_HOOK_END,
            )
        except ValueError as exc:
            return conflict(path, f"Cannot update managed Codex hook block: {exc}"), warnings

    if tomllib is not None:
        try:
            tomllib.loads(updated)
        except tomllib.TOMLDecodeError as exc:
            return conflict(path, f"Generated Codex TOML did not validate: {exc}"), warnings
    return classify_change(path, updated, "Ensured Codex context meter"), warnings


def has_inline_codex_hooks(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*\[\[?hooks(?:\.|\])", text))


def runtime_asset(name: str) -> str:
    path = Path(__file__).resolve().parents[1] / "assets" / "runtime" / name
    return path.read_text(encoding="utf-8")


def tracked_large_files(root: Path, threshold_kb: int) -> list[tuple[str, int]]:
    result = run_git(root, "ls-files", "-z")
    if result.returncode != 0:
        return []
    files: list[tuple[str, int]] = []
    for relative in result.stdout.split("\0"):
        if not relative:
            continue
        path = root / relative
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > threshold_kb * 1024:
            files.append((relative, size))
    return sorted(files, key=lambda item: item[1], reverse=True)


def render_diff(change: Change, root: Path) -> str:
    if not change.changed or change.new is None:
        return ""
    path = Path(change.path)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = str(path)
    old_lines = normalize_newlines(change.old or "").splitlines(keepends=True)
    new_lines = normalize_newlines(change.new).splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
    )


def build_plan(root: Path, args: argparse.Namespace) -> tuple[list[Change], list[WarningItem], set[str], dict[str, Any]]:
    changes: list[Change] = []
    warnings: list[WarningItem] = []
    ecosystems = detect_ecosystems(root)

    def destination(relative: Path) -> Optional[Path]:
        path, error = resolve_managed_destination(root, relative)
        if error:
            changes.append(
                Change(path=str(root / relative), status="conflict", note=error)
            )
            return None
        return path

    config_path = destination(Path(".shrinkydink.json"))
    config, config_error = ({}, None)
    if config_path is not None:
        config, config_error = load_json_object(config_path)
    effective = desired_config(config if not config_error else {}, args)
    config_validation = validate_config(effective)
    if config_path is None:
        effective = desired_config({}, args)
    elif config_error or config_validation:
        details = config_error or "; ".join(config_validation)
        changes.append(conflict(config_path, f"Cannot merge shrinkydink configuration: {details}"))
        effective = desired_config({}, args)
    else:
        changes.append(classify_change(config_path, json_text(effective), "Repository settings"))

    threshold = effective["context_warning_percent"]
    ignore_name = Path(str(effective["agentsignore"])).as_posix()

    text_targets = [
        (
            Path(".gitignore"),
            gitignore_body(ecosystems),
            TEXT_START,
            TEXT_END,
            "Validated repository ignores",
            "prepend",
        ),
        (
            Path(".gitattributes"),
            gitattributes_body(),
            TEXT_START,
            TEXT_END,
            "Validated line endings and binary attributes",
            "prepend",
        ),
        (
            Path(ignore_name),
            agentsignore_body(ecosystems, ignore_name),
            TEXT_START,
            TEXT_END,
            "Created agent-specific context exclusions",
            "prepend",
        ),
        (
            Path("AGENTS.md"),
            agents_md_body(threshold, ignore_name),
            MD_START,
            MD_END,
            "Shared cross-agent instructions",
            "append",
        ),
    ]
    if not args.no_claude:
        text_targets.append(
            (
                Path("CLAUDE.md"),
                claude_md_body(ignore_name),
                MD_START,
                MD_END,
                "Claude imports shared AGENTS.md instructions",
                "append",
            )
        )

    for relative, body, start, end, note, placement in text_targets:
        path = destination(relative)
        if path is None:
            continue
        try:
            existing = read_text(path)
        except (OSError, UnicodeDecodeError) as exc:
            changes.append(conflict(path, f"Cannot read text file safely: {exc}"))
            continue
        try:
            new = merge_managed_block(existing, body, start, end, placement)
            changes.append(classify_change(path, new, note))
        except ValueError as exc:
            changes.append(conflict(path, f"Cannot update managed block: {exc}"))

    runtime_names: list[str] = []
    if not args.no_claude or not args.no_codex:
        runtime_names.extend(("guard.py", "agentsignore.py"))
    if not args.no_claude:
        runtime_names.append("claude_status.py")
    if not args.no_codex:
        runtime_names.append("codex_precompact.py")
    for name in runtime_names:
        path = destination(Path(".agent-tools") / "shrinkydink" / name)
        if path is None:
            continue
        try:
            change = classify_change(path, runtime_asset(name), "Installed runtime helper")
        except (OSError, UnicodeDecodeError) as exc:
            changes.append(conflict(path, f"Cannot read runtime destination safely: {exc}"))
            continue
        change.mode = 0o755
        changes.append(change)

    if not args.no_claude:
        claude_path = destination(Path(".claude") / "settings.local.json")
        if claude_path is not None:
            claude_change, claude_warnings = plan_claude_settings(claude_path)
            claude_change.mode = 0o600
            changes.append(claude_change)
            warnings.extend(claude_warnings)

    if not args.no_codex:
        codex_config_path = destination(Path(".codex") / "config.toml")
        inline_hooks = False
        if codex_config_path is not None:
            try:
                codex_config_existing = read_text(codex_config_path)
                inline_hooks = has_inline_codex_hooks(codex_config_existing)
                codex_config_change, codex_warnings = plan_codex_config(
                    codex_config_path, inline_hooks
                )
                changes.append(codex_config_change)
                warnings.extend(codex_warnings)
            except (OSError, UnicodeDecodeError) as exc:
                changes.append(conflict(codex_config_path, f"Cannot read Codex config safely: {exc}"))
        if not inline_hooks:
            codex_hooks_path = destination(Path(".codex") / "hooks.json")
            if codex_hooks_path is not None:
                changes.append(plan_codex_hooks_json(codex_hooks_path))
        else:
            codex_hooks_path, hooks_error = resolve_managed_destination(
                root, Path(".codex") / "hooks.json"
            )
            if hooks_error:
                changes.append(
                    Change(
                        path=str(root / ".codex" / "hooks.json"),
                        status="conflict",
                        note=hooks_error,
                    )
                )
            elif codex_hooks_path is not None and codex_hooks_path.exists():
                warnings.append(
                    WarningItem(
                        "codex",
                        "This project already has both inline Codex hooks and `.codex/hooks.json`; Codex will merge them and may warn at startup.",
                    )
                )

    large_threshold = int(effective.get("large_file_warning_kb", DEFAULT_LARGE_FILE_WARNING_KB))
    large_files = tracked_large_files(root, large_threshold)
    if large_files:
        sample = ", ".join(f"{path} ({size / 1024:.0f} KiB)" for path, size in large_files[:8])
        if len(large_files) > 8:
            sample += f", plus {len(large_files) - 8} more"
        warnings.append(
            WarningItem(
                "large-files",
                f"Tracked files above {large_threshold} KiB can consume context quickly: {sample}.",
            )
        )

    if not (root / ".git").exists():
        warnings.append(
            WarningItem(
                "repository",
                "No `.git` directory was found at the selected root; files were still planned, but Git-specific checks are limited.",
            )
        )

    return changes, warnings, ecosystems, effective


def mark_transaction_aborted(changes: list[Change], reason: str) -> None:
    for change in changes:
        if change.changed:
            original = change.note
            change.status = "conflict"
            change.note = f"{reason}; planned change: {original}"


def remove_created_directories(
    created: list[Path], warnings: list[WarningItem]
) -> None:
    for directory in reversed(created):
        try:
            directory.rmdir()
        except FileNotFoundError:
            continue
        except OSError as exc:
            warnings.append(
                WarningItem(
                    "rollback",
                    f"Could not remove transaction-created directory {directory}: {exc}",
                )
            )


def apply_changes(root: Path, changes: list[Change]) -> ApplyResult:
    warnings: list[WarningItem] = []
    candidates = [change for change in changes if change.changed and change.new is not None]

    # Revalidate the full set immediately before the first staging write.
    for change in candidates:
        path = Path(change.path)
        try:
            relative = path.relative_to(root)
        except ValueError:
            error = f"Managed destination is outside the repository: {path}"
        else:
            _, error = resolve_managed_destination(root, relative)
        if error is None and path.is_symlink():
            error = f"Refusing to replace symbolic link: {path}"
        if error is None and path.exists() and not path.is_file():
            error = f"Expected a regular file: {path}"
        if error is None and change.status == "create" and path.exists():
            error = f"Destination appeared after planning: {path}"
        if error is None and change.status == "update" and not path.exists():
            error = f"Destination disappeared after planning: {path}"
        if error is None and change.status == "update":
            try:
                current = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                error = f"Cannot re-read destination during apply preflight: {path}: {exc}"
            else:
                if current != change.old:
                    error = f"Destination changed after planning: {path}"
        if error is not None:
            mark_transaction_aborted(changes, f"Apply preflight failed: {error}")
            warnings.append(WarningItem("preflight", error))
            return ApplyResult(warnings, False, [], [])

    staged: list[StagedChange] = []
    created_directories: list[Path] = []
    try:
        for change in candidates:
            path = Path(change.path)
            missing: list[Path] = []
            current = path.parent
            while current != root and not current.exists():
                missing.append(current)
                current = current.parent
            for directory in reversed(missing):
                directory.mkdir()
                created_directories.append(directory)

            existed = path.exists()
            prior_bytes = path.read_bytes() if existed else None
            prior_mode = stat.S_IMODE(path.stat().st_mode) if existed else None
            mode = prior_mode if prior_mode is not None else change.mode or 0o644
            written_bytes = change.new.encode("utf-8")
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(written_bytes)
                os.chmod(temp_path, mode)
            except BaseException:
                try:
                    os.close(fd)
                except OSError:
                    pass
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
                raise
            staged.append(
                StagedChange(
                    change=change,
                    path=path,
                    temp_path=temp_path,
                    prior_bytes=prior_bytes,
                    prior_mode=prior_mode,
                    written_bytes=written_bytes,
                    written_hash=hashlib.sha256(written_bytes).hexdigest(),
                )
            )
    except (OSError, UnicodeError) as exc:
        for item in staged:
            try:
                item.temp_path.unlink()
            except FileNotFoundError:
                pass
        remove_created_directories(created_directories, warnings)
        reason = f"Apply staging failed before any replacement: {exc}"
        mark_transaction_aborted(changes, reason)
        warnings.append(WarningItem("write", reason))
        return ApplyResult(warnings, False, [], [])

    committed: list[StagedChange] = []
    try:
        for item in staged:
            os.replace(item.temp_path, item.path)
            committed.append(item)
    except OSError as exc:
        failed_path = item.path
        warnings.append(
            WarningItem(
                "write",
                f"Failed to replace {failed_path}: {exc}; rolling back "
                f"{len(committed)} changed destination(s)",
            )
        )
        restored: list[str] = []
        rollback_skipped: list[str] = []
        for applied in reversed(committed):
            try:
                current_bytes = applied.path.read_bytes()
            except OSError as read_exc:
                rollback_skipped.append(str(applied.path))
                warnings.append(
                    WarningItem(
                        "rollback",
                        f"Could not verify {applied.path} before rollback: {read_exc}; left unchanged",
                    )
                )
                continue
            current_hash = hashlib.sha256(current_bytes).hexdigest()
            if current_hash != applied.written_hash or current_bytes != applied.written_bytes:
                rollback_skipped.append(str(applied.path))
                warnings.append(
                    WarningItem(
                        "rollback",
                        f"Skipped rollback for independently changed {applied.path}",
                    )
                )
                continue
            try:
                if applied.prior_bytes is None:
                    applied.path.unlink()
                else:
                    fd, rollback_name = tempfile.mkstemp(
                        prefix=f".{applied.path.name}.rollback.",
                        dir=str(applied.path.parent),
                    )
                    rollback_path = Path(rollback_name)
                    try:
                        with os.fdopen(fd, "wb") as handle:
                            handle.write(applied.prior_bytes)
                        rollback_mode = (
                            applied.prior_mode
                            if applied.prior_mode is not None
                            else 0o644
                        )
                        os.chmod(rollback_path, rollback_mode)
                        os.replace(rollback_path, applied.path)
                    finally:
                        try:
                            rollback_path.unlink()
                        except FileNotFoundError:
                            pass
                restored.append(str(applied.path))
                warnings.append(WarningItem("rollback", f"Restored {applied.path}"))
            except OSError as rollback_exc:
                rollback_skipped.append(str(applied.path))
                warnings.append(
                    WarningItem(
                        "rollback",
                        f"Failed to restore {applied.path}: {rollback_exc}",
                    )
                )

        for staged_item in staged:
            try:
                staged_item.temp_path.unlink()
            except FileNotFoundError:
                pass
        remove_created_directories(created_directories, warnings)
        summary = (
            f"Apply transaction failed at {failed_path}; restored {len(restored)} "
            f"destination(s), skipped {len(rollback_skipped)} rollback(s)"
        )
        mark_transaction_aborted(changes, summary)
        return ApplyResult(warnings, False, restored, rollback_skipped)

    return ApplyResult(warnings, True, [], [])


def relative_path(path: str, root: Path) -> str:
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return path


def print_text_report(
    root: Path,
    mode: str,
    changes: list[Change],
    warnings: list[WarningItem],
    ecosystems: set[str],
    effective: dict[str, Any],
    show_diff: bool,
) -> None:
    print(f"Shrinkydink {mode}: {root}")
    print(f"Detected ecosystems: {', '.join(sorted(ecosystems)) or 'none'}")
    print(
        "Policy: "
        f"ignore_mode={effective.get('ignore_mode')}, "
        f"context_warning_percent={effective.get('context_warning_percent')}, "
        f"large_file_warning_kb={effective.get('large_file_warning_kb')}"
    )
    print()
    labels = {"create": "CREATE", "update": "UPDATE", "ok": "OK", "conflict": "CONFLICT"}
    for change in changes:
        print(f"{labels.get(change.status, change.status.upper()):8} {relative_path(change.path, root)}")
        if change.note:
            print(f"         {change.note}")
    if warnings:
        print("\nWarnings:")
        for item in warnings:
            print(f"- [{item.kind}] {item.message}")

    if show_diff:
        diffs = [render_diff(change, root) for change in changes if change.changed]
        diffs = [diff for diff in diffs if diff]
        if diffs:
            print("\nProposed changes:\n")
            print("\n".join(diffs), end="" if diffs[-1].endswith("\n") else "\n")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="Create or validate cross-agent repository context hygiene files."
    )
    parser.add_argument("--repo", default=".", help="Repository path (default: current directory)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply", action="store_true", help="Write the full validated change set transactionally"
    )
    mode.add_argument("--check", action="store_true", help="Exit 1 when drift or conflicts exist")
    mode.add_argument(
        "--check-agentsignore-conformance",
        action="store_true",
        help="Run the packaged .agentsignore conformance fixtures and exit",
    )
    parser.add_argument(
        "--context-warning-percent",
        type=int,
        choices=range(1, 100),
        metavar="1-99",
        help=f"Context usage warning threshold (default: {DEFAULT_CONTEXT_WARNING_PERCENT})",
    )
    parser.add_argument(
        "--ignore-mode",
        choices=("warn", "deny", "off"),
        help=f".agentsignore hook behavior (default: {DEFAULT_IGNORE_MODE})",
    )
    parser.add_argument(
        "--large-file-warning-kb",
        type=int,
        metavar="KB",
        help=f"Warn about larger tracked files (default: {DEFAULT_LARGE_FILE_WARNING_KB})",
    )
    parser.add_argument("--no-claude", action="store_true", help="Do not manage Claude files")
    parser.add_argument("--no-codex", action="store_true", help="Do not manage Codex files")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report")
    parser.add_argument(
        "--no-diff", action="store_true", help="Suppress unified diffs in audit/check output"
    )
    args = parser.parse_args(raw_argv)
    if args.large_file_warning_kb is not None and args.large_file_warning_kb < 1:
        parser.error("--large-file-warning-kb must be at least 1")
    if args.check_agentsignore_conformance:
        incompatible = []
        if any(value == "--repo" or value.startswith("--repo=") for value in raw_argv):
            incompatible.append("--repo")
        for option, value in (
            ("--context-warning-percent", args.context_warning_percent),
            ("--ignore-mode", args.ignore_mode),
            ("--large-file-warning-kb", args.large_file_warning_kb),
            ("--no-claude", args.no_claude),
            ("--no-codex", args.no_codex),
            ("--no-diff", args.no_diff),
        ):
            if value not in {None, False}:
                incompatible.append(option)
        if incompatible:
            parser.error(
                "--check-agentsignore-conformance cannot be combined with "
                + ", ".join(incompatible)
            )
    return args


def agentsignore_runtime() -> Any:
    runtime_directory = Path(__file__).resolve().parents[1] / "assets" / "runtime"
    runtime_text = str(runtime_directory)
    if runtime_text not in sys.path:
        sys.path.insert(0, runtime_text)
    import agentsignore

    return agentsignore


def print_conformance_report(report: dict[str, Any]) -> None:
    status = str(report.get("status", "error")).upper()
    print(
        f"Agentsignore conformance: {status} "
        f"({report.get('passed', 0)} passed, {report.get('failed', 0)} failed, "
        f"{report.get('skipped', 0)} skipped)"
    )
    for error in report.get("errors", []):
        print(f"ERROR  {error}")
    for suite in report.get("suites", []):
        cases = suite.get("cases", [])
        failed = [case for case in cases if case.get("status") == "fail"]
        skipped = [case for case in cases if case.get("status") == "skip"]
        print(
            f"{'PASS' if not failed else 'FAIL':5}  {suite.get('name')} "
            f"({len(cases) - len(failed) - len(skipped)}/{len(cases)} passed)"
        )
        for case in failed:
            print(
                f"       {case.get('id')}: expected {case.get('expected')}, "
                f"got {case.get('actual')}"
            )
        for case in skipped:
            print(f"SKIP   {case.get('id')}: platform capability unavailable")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.check_agentsignore_conformance:
        runtime = agentsignore_runtime()
        fixture_root = (
            Path(__file__).resolve().parents[1]
            / "tests"
            / "fixtures"
            / "agentsignore"
            / "v1"
        )
        report = runtime.run_conformance(fixture_root)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print_conformance_report(report)
        return runtime.conformance_exit_code(report)
    try:
        root = resolve_repo(args.repo)
    except ValueError as exc:
        print(f"shrinkydink: {exc}", file=sys.stderr)
        return 2

    mode = "apply" if args.apply else "check" if args.check else "audit"
    try:
        changes, warnings, ecosystems, effective = build_plan(root, args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"shrinkydink: failed to build plan: {exc}", file=sys.stderr)
        return 2

    if args.apply:
        conflicts = [change for change in changes if change.status == "conflict"]
        if conflicts:
            warnings.append(
                WarningItem(
                    "preflight",
                    f"Apply aborted before staging because {len(conflicts)} conflict(s) "
                    "must be resolved first; no destinations were written.",
                )
            )
        else:
            apply_result = apply_changes(root, changes)
            warnings.extend(apply_result.warnings)

    show_diff = not args.no_diff and not args.apply
    if args.json:
        payload = {
            "repo": str(root),
            "mode": mode,
            "ecosystems": sorted(ecosystems),
            "settings": effective,
            "changes": [
                {
                    "path": relative_path(change.path, root),
                    "status": change.status,
                    "note": change.note,
                    "old": change.old if show_diff and change.changed else None,
                    "new": change.new if show_diff and change.changed else None,
                }
                for change in changes
            ],
            "warnings": [asdict(item) for item in warnings],
        }
        print(json.dumps(payload, indent=2))
    else:
        print_text_report(
            root,
            mode,
            changes,
            warnings,
            ecosystems,
            effective,
            show_diff=show_diff,
        )

    has_conflict = any(change.status == "conflict" for change in changes)
    has_drift = any(change.changed for change in changes)
    if args.check and (has_conflict or has_drift):
        return 1
    if args.apply and has_conflict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
