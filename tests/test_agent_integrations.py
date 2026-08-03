from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_shrinkydink import run_main, shrinkydink


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "integrations" / "v1" / "scenarios.json"
SCENARIOS = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class AgentIntegrationTests(unittest.TestCase):
    def test_fresh_apply_uses_committed_claude_settings_and_safe_denies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            apply_code, apply_output = run_main(root, "--apply")
            second_code, second_output = run_main(root, "--apply")
            check_code, check_output = run_main(root, "--check", "--no-diff")

            self.assertEqual(apply_code, 0, apply_output)
            self.assertEqual(second_code, 0, second_output)
            self.assertEqual(check_code, 0, check_output)
            shared_path = root / ".claude" / "settings.json"
            local_path = root / ".claude" / "settings.local.json"
            self.assertTrue(shared_path.is_file())
            self.assertFalse(local_path.exists())
            settings = json.loads(shared_path.read_text(encoding="utf-8"))
            handler = settings["hooks"]["PreToolUse"][0]["hooks"][0]
            self.assertEqual(handler["command"], "python3")
            self.assertEqual(
                handler["args"],
                ["${CLAUDE_PROJECT_DIR}/.agent-tools/shrinkydink/guard.py"],
            )
            deny = settings["permissions"]["deny"]
            self.assertEqual(deny, shrinkydink.claude_native_deny_rules())
            self.assertFalse(any(".env.*" in rule for rule in deny))
            self.assertFalse(any("build" in rule or "node_modules" in rule for rule in deny))
            self.assertEqual(shrinkydink.validate_claude_settings(settings), [])
            self.assertEqual(
                shrinkydink.validate_codex_hooks(
                    json.loads((root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
                ),
                [],
            )

    def test_unrelated_configuration_and_status_lines_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / ".claude" / "settings.json", SCENARIOS["unrelated"]["claude"])
            write_json(root / ".codex" / "hooks.json", SCENARIOS["unrelated"]["codex"])
            config = root / ".codex" / "config.toml"
            config.write_text('[tui]\nstatus_line = ["model-with-reasoning"]\n', encoding="utf-8")

            apply_code, output = run_main(root, "--apply")
            check_code, check_output = run_main(root, "--check", "--no-diff")

            self.assertEqual(apply_code, 0, output)
            self.assertEqual(check_code, 0, check_output)
            claude = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(claude["permissions"]["allow"], ["Read(./docs/**)"])
            self.assertIn("Read(./private/**)", claude["permissions"]["deny"])
            self.assertEqual(claude["hooks"]["PreToolUse"][0]["matcher"], "^Read$")
            self.assertEqual(claude["statusLine"]["command"], "python3 tools/team_status.py")
            codex = json.loads((root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(codex["description"], "Team hooks")
            self.assertEqual(codex["hooks"]["PreToolUse"][0]["matcher"], "^Shell$")
            self.assertEqual(config.read_text(encoding="utf-8"), '[tui]\nstatus_line = ["model-with-reasoning"]\n')
            self.assertIn("statusLine` was preserved", output)
            self.assertIn("status_line` omits", output)

    def test_exact_managed_local_entries_migrate_without_creating_a_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / ".claude" / "settings.local.json"
            write_json(local, SCENARIOS["managed_local"])
            if os.name == "posix":
                local.chmod(0o640)

            audit_code, audit_output = run_main(root, "--json")
            audit = json.loads(audit_output)
            local_report = next(
                change for change in audit["changes"]
                if change["path"] == ".claude/settings.local.json"
            )
            self.assertEqual(audit_code, 0, audit_output)
            self.assertIsNone(local_report["old"])
            self.assertIsNone(local_report["new"])
            self.assertNotIn("keep-me", audit_output)

            apply_code, output = run_main(root, "--apply")

            self.assertEqual(apply_code, 0, output)
            migrated = json.loads(local.read_text(encoding="utf-8"))
            self.assertEqual(migrated["userSetting"], "keep-me")
            self.assertNotIn("hooks", migrated)
            self.assertNotIn("statusLine", migrated)
            self.assertTrue((root / ".claude" / "settings.json").is_file())
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(local.stat().st_mode), 0o640)
            check_code, check_output = run_main(root, "--check", "--no-diff")
            self.assertEqual(check_code, 0, check_output)

    def test_noncanonical_local_settings_are_preserved_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / ".claude" / "settings.local.json"
            local.parent.mkdir(parents=True)
            original = SCENARIOS["noncanonical_local"].encode("utf-8")
            local.write_bytes(original)

            apply_code, output = run_main(root, "--apply")

            self.assertEqual(apply_code, 0, output)
            self.assertEqual(local.read_bytes(), original)
            self.assertIn("preserved the file byte-for-byte", output)
            self.assertTrue((root / ".claude" / "settings.json").is_file())

    def test_root_safe_commands_work_from_nested_posix_and_render_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            apply_code, output = run_main(root, "--apply")
            self.assertEqual(apply_code, 0, output)
            nested = root / "src" / "nested"
            nested.mkdir(parents=True)
            payload = json.dumps(
                {"tool_name": "Read", "tool_input": {"file_path": "README.md"}, "cwd": str(nested)}
            )

            claude = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
            claude_handler = claude["hooks"]["PreToolUse"][0]["hooks"][0]
            claude_script = claude_handler["args"][0].replace("${CLAUDE_PROJECT_DIR}", str(root))
            claude_run = subprocess.run(
                [claude_handler["command"], claude_script],
                cwd=nested,
                input=payload,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(claude_run.returncode, 0, claude_run.stderr)

            codex = json.loads((root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            codex_handler = codex["hooks"]["PreToolUse"][0]["hooks"][0]
            codex_run = subprocess.run(
                codex_handler["command"],
                cwd=nested,
                input=payload,
                text=True,
                shell=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(codex_run.returncode, 0, codex_run.stderr)
            windows = codex_handler["commandWindows"]
            for required in SCENARIOS["commands"]["windows_requires"]:
                self.assertIn(required, windows)
            self.assertNotIn('py -3 ".agent-tools', windows)
            inline = shrinkydink.codex_inline_hook_body()
            self.assertEqual(shrinkydink.validate_codex_inline_hook_body(inline), [])
            self.assertIn("command_windows", inline)

    def test_inline_codex_hooks_preserve_the_existing_representation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / ".codex" / "config.toml"
            config.parent.mkdir(parents=True)
            config.write_text(
                'team_value = "keep"\n\n'
                '[[hooks.SessionStart]]\nmatcher = "startup"\n\n'
                '[[hooks.SessionStart.hooks]]\ntype = "command"\n'
                'command = "python3 tools/team_start.py"\n',
                encoding="utf-8",
            )

            apply_code, output = run_main(root, "--apply")
            check_code, check_output = run_main(root, "--check", "--no-diff")

            self.assertEqual(apply_code, 0, output)
            self.assertEqual(check_code, 0, check_output)
            self.assertFalse((root / ".codex" / "hooks.json").exists())
            rendered = config.read_text(encoding="utf-8")
            self.assertIn('team_value = "keep"', rendered)
            self.assertIn('command = "python3 tools/team_start.py"', rendered)
            self.assertIn("# shrinkydink:hooks:start", rendered)
            self.assertIn("git rev-parse --show-toplevel", rendered)
            self.assertIn("Join-Path $root", rendered)
            if shrinkydink.tomllib is not None:
                shrinkydink.tomllib.loads(rendered)

    def test_audit_metadata_distinguishes_shared_local_and_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(
                root / ".claude" / "settings.local.json",
                {"statusLine": {"type": "command", "command": "python3 tools/personal_status.py"}},
            )
            apply_code, apply_output = run_main(root, "--apply")
            self.assertEqual(apply_code, 0, apply_output)
            self.assertIn("Local scalar precedence may hide", apply_output)

            json_code, json_output = run_main(root, "--check", "--no-diff", "--json")
            text_code, text_output = run_main(root, "--check", "--no-diff")

            self.assertEqual(json_code, 0, json_output)
            self.assertEqual(text_code, 0, text_output)
            report = json.loads(json_output)
            by_path = {change["path"]: change for change in report["changes"]}
            self.assertEqual(by_path[".claude/settings.json"]["treatment"], "shared-commit")
            self.assertEqual(by_path[".claude/settings.local.json"]["treatment"], "local-ignore")
            self.assertIn("/status", by_path[".claude/settings.json"]["integration"])
            self.assertIn("/hooks", by_path[".codex/hooks.json"]["integration"])
            self.assertIn("Treatment: shared-commit", text_output)
            self.assertIn("Treatment: local-ignore", text_output)
            self.assertIn("Activation:", text_output)

    def test_invalid_client_shapes_block_the_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / ".claude" / "settings.json", {"hooks": "not-an-object"})

            apply_code, output = run_main(root, "--apply")

            self.assertEqual(apply_code, 1, output)
            self.assertIn("Cannot merge Claude hooks safely", output)
            self.assertFalse((root / ".gitignore").exists())
            self.assertEqual(
                json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8")),
                {"hooks": "not-an-object"},
            )


if __name__ == "__main__":
    unittest.main()
