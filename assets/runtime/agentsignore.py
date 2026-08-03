#!/usr/bin/env python3
"""Canonical, dependency-free matcher for Shrinkydink's .agentsignore contract."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


PATH_FILE = "file"
PATH_DIRECTORY = "directory"


@dataclass(frozen=True)
class Rule:
    raw: str
    pattern: str
    negated: bool
    directory_only: bool
    anchored: bool
    has_slash: bool
    regex: re.Pattern[str]

    @property
    def identity(self) -> str:
        return self.pattern.lstrip("/").rstrip("/")

    def matches_node(self, relative_path: str, kind: str) -> bool:
        if self.directory_only and kind != PATH_DIRECTORY:
            return False
        return self.regex.match(relative_path) is not None


@dataclass(frozen=True)
class MatchResult:
    ignored: bool
    rule: Optional[Rule]


@dataclass(frozen=True)
class NormalizedPath:
    state: str
    relative: Optional[str]
    kind: str


def _trim_unescaped_trailing_spaces(value: str) -> str:
    end = len(value)
    while end and value[end - 1] == " ":
        backslashes = 0
        cursor = end - 2
        while cursor >= 0 and value[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            break
        end -= 1
    return value[:end]


def _class_regex(pattern: str, start: int) -> tuple[str, int]:
    cursor = start + 1
    if cursor >= len(pattern):
        return re.escape("["), start
    negate = ""
    if pattern[cursor] in {"!", "^"}:
        negate = "^"
        cursor += 1
    content: list[str] = []
    if cursor < len(pattern) and pattern[cursor] == "]":
        content.append(r"\]")
        cursor += 1
    while cursor < len(pattern) and pattern[cursor] != "]":
        char = pattern[cursor]
        if char == "\\" and cursor + 1 < len(pattern):
            cursor += 1
            content.append(re.escape(pattern[cursor]))
        elif char == "\\":
            content.append(r"\\")
        elif char == "^" and not content:
            content.append(r"\^")
        else:
            content.append(char)
        cursor += 1
    if cursor >= len(pattern):
        return re.escape("["), start
    return "[" + negate + "".join(content) + "]", cursor


def _glob_regex(pattern: str, anchored: bool, has_slash: bool) -> re.Pattern[str]:
    chunks: list[str] = []
    cursor = 0
    while cursor < len(pattern):
        char = pattern[cursor]
        if char == "\\":
            if cursor + 1 < len(pattern):
                cursor += 1
                chunks.append(re.escape(pattern[cursor]))
            else:
                chunks.append(re.escape("\\"))
        elif char == "*":
            star_end = cursor
            while star_end + 1 < len(pattern) and pattern[star_end + 1] == "*":
                star_end += 1
            if star_end > cursor:
                after = pattern[star_end + 1] if star_end + 1 < len(pattern) else ""
                before = pattern[cursor - 1] if cursor else ""
                whole_component = (not before or before == "/") and (
                    not after or after == "/"
                )
                if whole_component and after == "/":
                    chunks.append("(?:.*/)?")
                    star_end += 1
                elif whole_component:
                    chunks.append(".*")
                else:
                    chunks.append("[^/]*")
                cursor = star_end
            else:
                chunks.append("[^/]*")
        elif char == "?":
            chunks.append("[^/]")
        elif char == "[":
            expression, cursor = _class_regex(pattern, cursor)
            chunks.append(expression)
        else:
            chunks.append(re.escape(char))
        cursor += 1

    prefix = "^" if anchored or has_slash else r"^(?:.*/)?"
    return re.compile(prefix + "".join(chunks) + "$", re.DOTALL)


def parse_rule_lines(lines: Iterable[str]) -> tuple[Rule, ...]:
    rules: list[Rule] = []
    for original in lines:
        line = original.rstrip("\r\n")
        line = _trim_unescaped_trailing_spaces(line)
        if not line or line.startswith("#"):
            continue

        negated = line.startswith("!")
        if negated:
            line = line[1:]
        elif line.startswith((r"\#", r"\!")):
            line = line[1:]
        if not line:
            continue

        directory_only = line.endswith("/") and not line.endswith(r"\/")
        if directory_only:
            line = line[:-1]
        anchored = line.startswith("/")
        if anchored:
            line = line[1:]
        if not line:
            continue
        has_slash = "/" in line
        try:
            regex = _glob_regex(line, anchored, has_slash)
        except re.error:
            continue
        rules.append(
            Rule(
                raw=original.rstrip("\r\n"),
                pattern=("/" if anchored else "") + line,
                negated=negated,
                directory_only=directory_only,
                anchored=anchored,
                has_slash=has_slash,
                regex=regex,
            )
        )
    return tuple(rules)


def parse_rules_text(text: str) -> tuple[Rule, ...]:
    return parse_rule_lines(text.splitlines(keepends=True))


def _literal_prefix(pattern: str) -> str:
    escaped = False
    result: list[str] = []
    for char in pattern.lstrip("/"):
        if escaped:
            result.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char in "*?[":
            break
        else:
            result.append(char)
    return "".join(result).rstrip("/")


def _exclusion_key(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    if normalized.startswith("!"):
        normalized = normalized[1:]
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/").rstrip("/")
    if normalized.endswith("/**"):
        normalized = normalized[:-3].rstrip("/")
    return normalized


class AgentsIgnoreMatcher:
    """Parse once, then match typed repository-relative paths consistently."""

    def __init__(self, rules: Iterable[Rule]) -> None:
        self.rules = tuple(rules)

    @classmethod
    def from_text(cls, text: str) -> "AgentsIgnoreMatcher":
        return cls(parse_rules_text(text))

    @classmethod
    def from_file(cls, path: Path) -> "AgentsIgnoreMatcher":
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        return cls.from_text(text)

    @property
    def active_ignore_rules(self) -> tuple[Rule, ...]:
        active: dict[tuple[str, bool], Rule] = {}
        for rule in self.rules:
            if rule.negated:
                active.pop((rule.identity, rule.directory_only), None)
                if not rule.directory_only:
                    active.pop((rule.identity, True), None)
            else:
                active[(rule.identity, rule.directory_only)] = rule
        return tuple(active.values())

    def match(self, relative_path: str, kind: str = PATH_FILE) -> MatchResult:
        normalized = relative_path.replace("\\", "/").strip("/")
        if not normalized:
            return MatchResult(False, None)
        components = normalized.split("/")
        parent_ignored = False
        matched_rule: Optional[Rule] = None
        for index in range(1, len(components) + 1):
            node = "/".join(components[:index])
            node_kind = PATH_DIRECTORY if index < len(components) else kind
            ignored = parent_ignored
            node_rule = matched_rule if parent_ignored else None
            for rule in self.rules:
                if not rule.matches_node(node, node_kind):
                    continue
                if rule.negated:
                    if not parent_ignored:
                        ignored = False
                        node_rule = None
                else:
                    ignored = True
                    node_rule = rule
            parent_ignored = ignored
            matched_rule = node_rule if ignored else None
        return MatchResult(parent_ignored, matched_rule)

    def normalize(
        self,
        candidate: str,
        root: Path,
        cwd: Path,
        kind: str = PATH_FILE,
    ) -> NormalizedPath:
        if kind not in {PATH_FILE, PATH_DIRECTORY}:
            return NormalizedPath("invalid", None, kind)
        if not isinstance(candidate, str) or not candidate:
            return NormalizedPath("invalid", None, kind)
        spelling = candidate.replace("\\", "/")
        try:
            path = Path(spelling).expanduser()
            if not path.is_absolute():
                path = cwd / path
            resolved_root = root.resolve(strict=False)
            resolved = path.resolve(strict=False)
            relative = resolved.relative_to(resolved_root).as_posix()
        except (OSError, RuntimeError, ValueError):
            return NormalizedPath("outside", None, kind)
        return NormalizedPath("inside", "" if relative == "." else relative, kind)

    def may_ignore_under(self, relative_scope: str) -> bool:
        scope = relative_scope.replace("\\", "/").strip("/")
        for rule in self.active_ignore_rules:
            pattern = rule.pattern.lstrip("/")
            if not rule.anchored and "/" not in pattern:
                return True
            prefix = _literal_prefix(pattern)
            if not prefix or not scope:
                return True
            if (
                prefix == scope
                or prefix.startswith(scope + "/")
                or scope.startswith(prefix + "/")
            ):
                return True
        return False

    def exclusions_cover(self, exclusions: Iterable[str]) -> bool:
        keys = {_exclusion_key(value) for value in exclusions if _exclusion_key(value)}
        required = {_exclusion_key(rule.pattern) for rule in self.active_ignore_rules}
        return bool(required) and required.issubset(keys)


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _materialize_tree(root: Path, outside: Path, tree: dict[str, Any]) -> set[str]:
    nodes = tree.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("tree.json must contain a nodes array")
    unavailable: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("path"), str):
            raise ValueError("each tree node needs a string path")
        if node.get("kind") == PATH_DIRECTORY:
            (root / node["path"]).mkdir(parents=True, exist_ok=True)
    for node in nodes:
        path = root / node["path"]
        kind = node.get("kind")
        if kind == PATH_FILE:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        elif kind == "symlink":
            path.parent.mkdir(parents=True, exist_ok=True)
            target_value = node.get("target")
            if not isinstance(target_value, str):
                raise ValueError("symlink nodes need a string target")
            target = outside if target_value == "$OUTSIDE" else Path(target_value)
            try:
                path.symlink_to(target, target_is_directory=True)
            except (NotImplementedError, OSError):
                unavailable.add(node["path"])
        elif kind != PATH_DIRECTORY:
            raise ValueError(f"unsupported tree node kind: {kind!r}")
    return unavailable


def _run_suite(
    fixture_root: Path,
    manifest_name: str,
    repo: Path,
    unavailable: set[str],
) -> dict[str, Any]:
    manifest = _load_json_object(fixture_root / manifest_name)
    suite = manifest.get("suite")
    rules_name = manifest.get("rules")
    cases = manifest.get("cases")
    if manifest.get("version") != 1 or not isinstance(suite, str):
        raise ValueError(f"{manifest_name} has an unsupported version or suite")
    if not isinstance(rules_name, str) or not isinstance(cases, list):
        raise ValueError(f"{manifest_name} needs rules and cases")
    try:
        matcher = AgentsIgnoreMatcher.from_text(
            (fixture_root / rules_name).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot load {rules_name}: {exc}") from exc

    reports: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError(f"{manifest_name} contains a non-object case")
        case_id = case.get("id")
        candidate = case.get("candidate")
        kind = case.get("kind")
        expected = case.get("expected")
        if (
            not isinstance(case_id, str)
            or not isinstance(candidate, str)
            or kind not in {PATH_FILE, PATH_DIRECTORY}
            or expected not in {"included", "excluded", "rejected"}
        ):
            raise ValueError(f"{manifest_name} contains an invalid case")
        requires = case.get("requires")
        if requires == "symlink" and any(
            candidate == item or candidate.startswith(item + "/") for item in unavailable
        ):
            reports.append({"id": case_id, "status": "skip", "expected": expected})
            continue
        cwd_value = case.get("cwd", ".")
        if not isinstance(cwd_value, str):
            raise ValueError(f"{case_id} has an invalid cwd")
        cwd = repo / cwd_value
        normalized = matcher.normalize(candidate, repo, cwd, kind)
        if normalized.state != "inside":
            actual = "rejected"
        else:
            result = matcher.match(normalized.relative or "", kind)
            actual = "excluded" if result.ignored else "included"
        reports.append(
            {
                "id": case_id,
                "status": "pass" if actual == expected else "fail",
                "expected": expected,
                "actual": actual,
            }
        )
    return {"name": suite, "cases": reports}


def run_conformance(fixture_root: Path) -> dict[str, Any]:
    """Run packaged v1 fixtures without reading a target repository."""
    try:
        tree = _load_json_object(fixture_root / "tree.json")
        if tree.get("version") != 1:
            raise ValueError("tree.json has an unsupported version")
        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as outside_dir:
            repo = Path(repo_dir)
            outside = Path(outside_dir)
            unavailable = _materialize_tree(repo, outside, tree)
            suites = [
                _run_suite(fixture_root, "expected.json", repo, unavailable),
                _run_suite(fixture_root, "docker-agent-expected.json", repo, unavailable),
            ]
    except (OSError, ValueError) as exc:
        return {
            "version": 1,
            "status": "error",
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [str(exc)],
            "suites": [],
        }

    reports = [case for suite in suites for case in suite["cases"]]
    passed = sum(case["status"] == "pass" for case in reports)
    failed = sum(case["status"] == "fail" for case in reports)
    skipped = sum(case["status"] == "skip" for case in reports)
    return {
        "version": 1,
        "status": "fail" if failed else "pass",
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": [],
        "suites": suites,
    }


def conformance_exit_code(report: dict[str, Any]) -> int:
    if report.get("status") == "error":
        return 2
    return 1 if report.get("failed") else 0
