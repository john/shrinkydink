from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = PROJECT_ROOT / "assets" / "runtime" / "guard.py"
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "hooks"
SPEC = importlib.util.spec_from_file_location("shrinkydink_guard", GUARD_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {GUARD_PATH}")
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


CLAUDE_FIXTURE = load_fixture("claude-pre-tool-use.json")
CODEX_FIXTURE = load_fixture("codex-pre-tool-use.json")


def validate_common_output(output: Any, expect_deny: bool) -> None:
    if not isinstance(output, dict):
        raise AssertionError("hook output must be a JSON object")
    if set(output) != {"systemMessage", "hookSpecificOutput"}:
        raise AssertionError("hook output has missing or unknown top-level fields")
    if not isinstance(output["systemMessage"], str) or not output["systemMessage"]:
        raise AssertionError("systemMessage must be a non-empty string")

    hook = output["hookSpecificOutput"]
    if not isinstance(hook, dict):
        raise AssertionError("hookSpecificOutput must be an object")
    allowed = {
        "hookEventName",
        "additionalContext",
        "permissionDecision",
        "permissionDecisionReason",
    }
    if not set(hook).issubset(allowed):
        raise AssertionError("hookSpecificOutput has unknown fields")
    if hook.get("hookEventName") != "PreToolUse":
        raise AssertionError("hookEventName must be PreToolUse")
    if not isinstance(hook.get("additionalContext"), str) or not hook["additionalContext"]:
        raise AssertionError("additionalContext must be a non-empty string")

    if expect_deny:
        if hook.get("permissionDecision") != "deny":
            raise AssertionError("denial must use permissionDecision=deny")
        if not isinstance(hook.get("permissionDecisionReason"), str):
            raise AssertionError("denial must include permissionDecisionReason")
    elif "permissionDecision" in hook or "permissionDecisionReason" in hook:
        raise AssertionError("advisory output must not carry a permission decision")


def validate_claude_output(output: Any, expect_deny: bool) -> None:
    validate_common_output(output, expect_deny)


def validate_codex_output(output: Any, expect_deny: bool) -> None:
    validate_common_output(output, expect_deny)


class GuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def payload(
        self, platform: str, tool_name: str, tool_input: Any, cwd: Optional[Path] = None
    ) -> dict[str, Any]:
        base = CLAUDE_FIXTURE if platform == "claude" else CODEX_FIXTURE
        payload = copy.deepcopy(base)
        payload["cwd"] = str(cwd or self.root)
        payload["tool_name"] = tool_name
        payload["tool_input"] = tool_input
        return payload

    def configure(self, rules: str, mode: str = "warn") -> None:
        (self.root / ".shrinkydink.json").write_text(
            json.dumps({"ignore_mode": mode, "agentsignore": ".agentsignore"}),
            encoding="utf-8",
        )
        (self.root / ".agentsignore").write_text(rules, encoding="utf-8")

    def invoke_configured(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        stdin = io.StringIO(json.dumps(payload))
        stdout = io.StringIO()
        with mock.patch.object(guard, "repo_root", return_value=self.root), mock.patch.object(
            guard.sys, "stdin", stdin
        ), contextlib.redirect_stdout(stdout):
            result = guard.main()
        self.assertEqual(result, 0)
        rendered = stdout.getvalue()
        return json.loads(rendered) if rendered else None

    def invoke(
        self,
        payload: dict[str, Any],
        rules: str,
        mode: str = "warn",
    ) -> Optional[dict[str, Any]]:
        self.configure(rules, mode)
        return self.invoke_configured(payload)

    def assert_warning(self, output: Optional[dict[str, Any]]) -> dict[str, Any]:
        self.assertIsNotNone(output)
        assert output is not None
        validate_claude_output(output, expect_deny=False)
        validate_codex_output(output, expect_deny=False)
        return output

    def assert_denial(self, output: Optional[dict[str, Any]]) -> dict[str, Any]:
        self.assertIsNotNone(output)
        assert output is not None
        validate_claude_output(output, expect_deny=True)
        validate_codex_output(output, expect_deny=True)
        return output

    def test_scalar_nested_and_list_paths_for_both_platforms(self) -> None:
        shapes = (
            {"file_path": "private.pem"},
            {"request": {"file": "private.pem"}},
            {"files": ["safe.txt", "private.pem"]},
            {"paths": [{"value": "safe.txt"}, {"value": "private.pem"}]},
        )
        for platform in ("claude", "codex"):
            for tool_input in shapes:
                with self.subTest(platform=platform, tool_input=tool_input):
                    output = self.assert_warning(
                        self.invoke(self.payload(platform, "Read", tool_input), "private.pem\n")
                    )
                    self.assertIn("private.pem (rule: private.pem)", output["systemMessage"])

    def test_every_supported_tool_has_a_matching_fixture(self) -> None:
        cases = (
            ("claude", "Read", {"file_path": "private.pem"}),
            ("claude", "Write", {"file_path": "private.pem", "content": "DO_NOT_ECHO"}),
            (
                "claude",
                "Edit",
                {"file_path": "private.pem", "old_string": "DO_NOT_ECHO", "new_string": "x"},
            ),
            ("claude", "Glob", {"pattern": "build/**"}),
            ("claude", "Grep", {"pattern": "needle", "path": "build"}),
            ("claude", "Bash", {"command": "cat private.pem"}),
            ("codex", "Read", {"file_path": "private.pem"}),
            ("codex", "Write", {"file_path": "private.pem", "content": "DO_NOT_ECHO"}),
            (
                "codex",
                "Edit",
                {"file_path": "private.pem", "old_string": "DO_NOT_ECHO", "new_string": "x"},
            ),
            ("codex", "Glob", {"pattern": "build/**"}),
            ("codex", "Grep", {"pattern": "needle", "path": "build"}),
            ("codex", "Bash", {"command": "cat private.pem"}),
            (
                "codex",
                "apply_patch",
                {"command": "*** Begin Patch\n*** Update File: private.pem\n*** End Patch"},
            ),
        )
        for platform, tool_name, tool_input in cases:
            with self.subTest(platform=platform, tool=tool_name):
                output = self.assert_warning(
                    self.invoke(
                        self.payload(platform, tool_name, tool_input),
                        "private.pem\nbuild/\n",
                    )
                )
                self.assertNotIn("DO_NOT_ECHO", output["systemMessage"])

    def test_bare_shell_operands_are_paths(self) -> None:
        commands = (
            "cat private.pem",
            "head -n 5 private.pem",
            "cp private.pem copy.pem",
            "cp safe.txt private.pem",
            "rm build/output.bin",
        )
        for command in commands:
            with self.subTest(command=command):
                output = self.assert_warning(
                    self.invoke(
                        self.payload("claude", "Bash", {"command": command}),
                        "private.pem\nbuild/\n",
                    )
                )
                self.assertIn("rule:", output["systemMessage"])

    def test_search_expression_is_not_treated_as_a_path(self) -> None:
        scoped = self.payload("claude", "Bash", {"command": "rg private.pem src/"})
        self.assertIsNone(self.invoke(scoped, "/private.pem\n"))

        direct = self.payload(
            "claude", "Grep", {"pattern": "private.pem", "path": "src/"}
        )
        self.assertIsNone(self.invoke(direct, "/private.pem\n"))

        unscoped = self.payload("claude", "Bash", {"command": "rg private.pem"})
        output = self.assert_warning(self.invoke(unscoped, "/private.pem\n"))
        self.assertIn("broad operation", output["systemMessage"])

    def test_content_fields_are_not_treated_as_paths(self) -> None:
        payload = self.payload(
            "claude",
            "Write",
            {"file_path": "src/main.py", "content": "private.pem"},
        )
        self.assertIsNone(self.invoke(payload, "/private.pem\n"))

    def test_apply_patch_headers_are_paths(self) -> None:
        headers = (
            "*** Add File: private.pem",
            "*** Update File: private.pem",
            "*** Delete File: private.pem",
            "*** Move to: private.pem",
            "*** Move to File: private.pem",
        )
        for header in headers:
            with self.subTest(header=header):
                command = f"*** Begin Patch\n{header}\n*** End Patch"
                self.assert_warning(
                    self.invoke(
                        self.payload("codex", "apply_patch", {"command": command}),
                        "private.pem\n",
                    )
                )

    def test_broad_operations_block_in_deny_mode(self) -> None:
        cases = (
            ("Grep", {"pattern": "needle"}),
            ("Glob", {"pattern": "**/*"}),
            ("Bash", {"command": "rg needle"}),
            ("Bash", {"command": "grep -R needle"}),
            ("Bash", {"command": "fd needle"}),
            ("Bash", {"command": "find"}),
            ("Bash", {"command": "ls -R"}),
        )
        for tool_name, tool_input in cases:
            with self.subTest(tool=tool_name, tool_input=tool_input):
                output = self.assert_denial(
                    self.invoke(
                        self.payload("claude", tool_name, tool_input),
                        "/build/\n",
                        mode="deny",
                    )
                )
                self.assertIn("narrower target", output["systemMessage"])
                self.assertIn("/build/", output["systemMessage"])

    def test_warn_mode_supplies_context_without_reading_ignored_content(self) -> None:
        ignored = self.root / "build" / "secret.txt"
        ignored.parent.mkdir()
        sentinel = "SENTINEL_SECRET_CONTENT"
        ignored.write_text(sentinel, encoding="utf-8")
        output = self.assert_warning(
            self.invoke(
                self.payload("codex", "Grep", {"pattern": "needle"}),
                "/build/\n",
            )
        )
        self.assertEqual(output["systemMessage"], output["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn(sentinel, json.dumps(output))

    def test_nonmatching_and_proven_safe_scopes_are_silent(self) -> None:
        cases = (
            ("Read", {"file_path": "src/main.py"}),
            ("Grep", {"pattern": "needle", "path": "src/"}),
            ("Glob", {"pattern": "src/**/*.py"}),
            ("Bash", {"command": "rg needle src/"}),
        )
        for tool_name, tool_input in cases:
            with self.subTest(tool=tool_name):
                self.assertIsNone(
                    self.invoke(
                        self.payload("claude", tool_name, tool_input),
                        "/build/\n",
                    )
                )

    def test_absolute_relative_and_subdirectory_paths(self) -> None:
        (self.root / "src").mkdir()
        cases = (
            (self.root, str(self.root / "private.pem")),
            (self.root, "./private.pem"),
            (self.root / "src", "../private.pem"),
        )
        for cwd, path in cases:
            with self.subTest(cwd=cwd, path=path):
                self.assert_warning(
                    self.invoke(
                        self.payload("codex", "Read", {"file_path": path}, cwd=cwd),
                        "/private.pem\n",
                    )
                )

        shell_payload = self.payload(
            "codex", "Bash", {"command": "cat ../private.pem"}, cwd=self.root / "src"
        )
        self.assert_warning(self.invoke(shell_payload, "/private.pem\n"))

    def test_directory_only_negation_separator_and_symlink_integration(self) -> None:
        build_file = self.root / "build"
        build_file.touch()
        payload = self.payload("codex", "Read", {"file_path": "build"})
        self.assertIsNone(self.invoke(payload, "build/\n"))
        build_file.unlink()
        build_file.mkdir()
        self.assert_warning(self.invoke(payload, "build/\n"))
        self.assert_warning(
            self.invoke(
                self.payload("codex", "Read", {"file_path": "parent/child.txt"}),
                "parent/\n!parent/child.txt\n",
            )
        )
        self.assertIsNone(
            self.invoke(
                self.payload("codex", "Read", {"file_path": "working\\child.txt"}),
                "working/*\n!working/child.txt\n",
            )
        )

        if hasattr(os, "symlink"):
            with tempfile.TemporaryDirectory() as outside_directory:
                outside = Path(outside_directory)
                try:
                    (self.root / "outside").symlink_to(outside, target_is_directory=True)
                except OSError as exc:
                    self.skipTest(f"symbolic links are unavailable: {exc}")
                self.assertIsNone(
                    self.invoke(
                        self.payload(
                            "codex", "Read", {"file_path": "outside/private.pem"}
                        ),
                        "*.pem\n",
                    )
                )

    def test_complete_explicit_exclusions_prove_broad_search_safe(self) -> None:
        commands = (
            "rg needle -g '!build/**'",
            "grep -R needle . --exclude-dir=build",
            "fd needle -E build",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(
                    self.invoke(
                        self.payload("codex", "Bash", {"command": command}),
                        "build/\n",
                        mode="deny",
                    )
                )

        partial = self.invoke(
            self.payload("codex", "Bash", {"command": "rg needle -g '!build/**'"}),
            "build/\ndist/\n",
            mode="deny",
        )
        self.assert_denial(partial)

    def test_off_empty_and_exactly_negated_rules_are_silent(self) -> None:
        payload = self.payload("claude", "Read", {"file_path": "private.pem"})
        self.assertIsNone(self.invoke(payload, "", mode="warn"))
        self.assertIsNone(self.invoke(payload, "private.pem\n", mode="off"))
        self.assertIsNone(self.invoke(payload, "private.pem\n!private.pem\n", mode="warn"))

    def test_messages_truncate_path_details(self) -> None:
        paths = [f"secret-{index}.pem" for index in range(5)]
        output = self.assert_warning(
            self.invoke(
                self.payload("codex", "Read", {"files": paths}),
                "*.pem\n",
            )
        )
        self.assertIn("plus 1 more", output["systemMessage"])

    def test_contract_validators_reject_malformed_output(self) -> None:
        malformed = (
            ({}, False),
            ({"systemMessage": 3, "hookSpecificOutput": {}}, False),
            (
                {
                    "systemMessage": "warning",
                    "hookSpecificOutput": {
                        "hookEventName": "WrongEvent",
                        "additionalContext": "warning",
                    },
                },
                False,
            ),
            (
                {
                    "systemMessage": "blocked",
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": "blocked",
                        "permissionDecision": "deny",
                    },
                },
                True,
            ),
        )
        for output, expect_deny in malformed:
            for validator in (validate_claude_output, validate_codex_output):
                with self.subTest(output=output, validator=validator.__name__):
                    with self.assertRaises(AssertionError):
                        validator(output, expect_deny)

    def test_guard_performance_budget_and_no_repository_walk(self) -> None:
        self.configure("/build/\n", mode="deny")
        payload = self.payload("codex", "Read", {"file_path": "build/output.bin"})
        with mock.patch.object(
            guard.Path, "rglob", side_effect=AssertionError("repository walk")
        ), mock.patch.object(guard.os, "walk", side_effect=AssertionError("repository walk")):
            started = time.perf_counter()
            for _ in range(50):
                self.assert_denial(self.invoke_configured(payload))
            elapsed = time.perf_counter() - started
        self.assertLessEqual(elapsed, 1.0, f"50 guard calls took {elapsed:.3f}s")


if __name__ == "__main__":
    unittest.main()
