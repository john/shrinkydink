from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "shrinkydink.py"
SPEC = importlib.util.spec_from_file_location("shrinkydink_script", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {SCRIPT_PATH}")
shrinkydink = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shrinkydink
SPEC.loader.exec_module(shrinkydink)


def run_main(root: Path, *arguments: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        result = shrinkydink.main(["--repo", str(root), *arguments])
    return result, output.getvalue()


def tree_snapshot(root: Path) -> dict[str, tuple[str, int, int, int]]:
    snapshot: dict[str, tuple[str, int, int, int]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        details = path.lstat()
        kind = "symlink" if path.is_symlink() else "dir" if path.is_dir() else "file"
        snapshot[relative] = (
            kind,
            details.st_size,
            details.st_mtime_ns,
            stat.S_IMODE(details.st_mode),
        )
    return snapshot


def file_state(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (
            path.read_bytes(),
            stat.S_IMODE(path.stat().st_mode),
        )
        for path in root.rglob("*")
        if path.is_file()
    }


class ShrinkydinkTests(unittest.TestCase):
    def test_audit_and_check_do_not_touch_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "existing.txt").write_text("keep\n", encoding="utf-8")
            before = tree_snapshot(root)

            audit_code, _ = run_main(root)
            after_audit = tree_snapshot(root)
            check_code, _ = run_main(root, "--check", "--no-diff")
            after_check = tree_snapshot(root)

            self.assertEqual(audit_code, 0)
            self.assertEqual(check_code, 1)
            self.assertEqual(after_audit, before)
            self.assertEqual(after_check, before)

    def test_custom_agentsignore_path_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {"agentsignore": "config/agent-ignore"}
            (root / ".shrinkydink.json").write_text(
                json.dumps(config), encoding="utf-8"
            )

            apply_code, output = run_main(root, "--apply")

            self.assertEqual(apply_code, 0, output)
            ignore_path = root / "config" / "agent-ignore"
            self.assertTrue(ignore_path.is_file())
            self.assertFalse((root / ".agentsignore").exists())
            self.assertIn("config/agent-ignore", ignore_path.read_text(encoding="utf-8"))
            self.assertIn("`config/agent-ignore`", (root / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertIn("`config/agent-ignore`", (root / "CLAUDE.md").read_text(encoding="utf-8"))

            guard = root / ".agent-tools" / "shrinkydink" / "guard.py"
            payload = {
                "tool_name": "Read",
                "tool_input": {"file_path": str(root / ".env")},
                "cwd": str(root),
            }
            guarded = subprocess.run(
                [sys.executable, str(guard)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(guarded.returncode, 0, guarded.stderr)
            self.assertIn("config/agent-ignore", guarded.stdout)
            self.assertIn(".env", guarded.stdout)

            (root / ".agentsignore").write_text("root-only-secret\n", encoding="utf-8")
            payload["tool_input"] = {"file_path": str(root / "root-only-secret")}
            stale = subprocess.run(
                [sys.executable, str(guard)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(stale.returncode, 0, stale.stderr)
            self.assertEqual(stale.stdout, "")

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_symlinked_parent_outside_repo_is_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(directory)
            outside = Path(outside_dir)
            try:
                (root / ".claude").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links are unavailable: {exc}")

            apply_code, output = run_main(root, "--apply")

            self.assertEqual(apply_code, 1, output)
            self.assertIn("resolves outside the repository", output)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse((root / ".gitignore").exists())
            self.assertFalse((root / ".shrinkydink.json").exists())

    def test_conflict_blocks_all_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            original = "user content\n<!-- shrinkydink:start -->\nunterminated\n"
            agents.write_text(original, encoding="utf-8")

            apply_code, output = run_main(root, "--apply")

            self.assertEqual(apply_code, 1, output)
            self.assertIn("Apply aborted before staging", output)
            self.assertEqual(agents.read_text(encoding="utf-8"), original)
            self.assertFalse((root / ".gitignore").exists())
            self.assertFalse((root / ".shrinkydink.json").exists())

    def test_invalid_config_blocks_all_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / ".shrinkydink.json"
            original = '{"ignore_mode": "invalid"}\n'
            config_path.write_text(original, encoding="utf-8")

            apply_code, output = run_main(root, "--apply")

            self.assertEqual(apply_code, 1, output)
            self.assertIn("Cannot merge shrinkydink configuration", output)
            self.assertEqual(config_path.read_text(encoding="utf-8"), original)
            self.assertEqual(sorted(path.name for path in root.iterdir()), [".shrinkydink.json"])

    def test_apply_preflight_detects_change_after_planning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            agents.write_text("original\n", encoding="utf-8")
            args = shrinkydink.parse_args(["--repo", str(root), "--apply"])
            changes, _, _, _ = shrinkydink.build_plan(root, args)
            agents.write_text("independent\n", encoding="utf-8")

            result = shrinkydink.apply_changes(root, changes)

            self.assertFalse(result.completed)
            self.assertIn("changed after planning", result.warnings[0].message)
            self.assertEqual(agents.read_text(encoding="utf-8"), "independent\n")
            self.assertFalse((root / ".shrinkydink.json").exists())

    def test_replacement_failure_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initial_code, initial_output = run_main(root, "--apply")
            self.assertEqual(initial_code, 0, initial_output)
            before = file_state(root)
            real_replace = os.replace
            calls = 0

            def fail_second_replace(source: object, destination: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated replacement failure")
                real_replace(source, destination)

            with mock.patch.object(shrinkydink.os, "replace", side_effect=fail_second_replace):
                apply_code, output = run_main(
                    root, "--apply", "--context-warning-percent", "71"
                )

            self.assertEqual(apply_code, 1, output)
            self.assertIn("simulated replacement failure", output)
            self.assertIn("Restored", output)
            self.assertEqual(file_state(root), before)

    def test_replacement_failure_removes_new_files_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_replace = os.replace
            calls = 0

            def fail_second_replace(source: object, destination: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated replacement failure")
                real_replace(source, destination)

            with mock.patch.object(shrinkydink.os, "replace", side_effect=fail_second_replace):
                apply_code, output = run_main(root, "--apply")

            self.assertEqual(apply_code, 1, output)
            self.assertIn("Restored", output)
            self.assertEqual(list(root.iterdir()), [])

    def test_rollback_does_not_overwrite_independent_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_replace = os.replace
            calls = 0

            def change_then_fail(source: object, destination: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    (root / ".shrinkydink.json").write_text(
                        "independent change\n", encoding="utf-8"
                    )
                    raise OSError("simulated replacement failure")
                real_replace(source, destination)

            with mock.patch.object(shrinkydink.os, "replace", side_effect=change_then_fail):
                apply_code, output = run_main(root, "--apply")

            self.assertEqual(apply_code, 1, output)
            self.assertIn("Skipped rollback for independently changed", output)
            self.assertEqual(
                (root / ".shrinkydink.json").read_text(encoding="utf-8"),
                "independent change\n",
            )

    @unittest.skipUnless(os.name == "posix", "POSIX file modes are unavailable")
    def test_permissions_preserved_and_assigned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gitignore = root / ".gitignore"
            gitignore.write_text("user-rule\n", encoding="utf-8")
            gitignore.chmod(0o640)

            apply_code, output = run_main(root, "--apply")

            self.assertEqual(apply_code, 0, output)
            self.assertEqual(stat.S_IMODE(gitignore.stat().st_mode), 0o640)
            settings = root / ".claude" / "settings.local.json"
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)
            for name in ("guard.py", "claude_status.py", "codex_precompact.py"):
                helper = root / ".agent-tools" / "shrinkydink" / name
                self.assertEqual(stat.S_IMODE(helper.stat().st_mode), 0o755)

    def test_apply_then_check_is_clean(self) -> None:
        for ignore_name in (".agentsignore", "config/agent-ignore"):
            with self.subTest(ignore_name=ignore_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if ignore_name != ".agentsignore":
                    (root / ".shrinkydink.json").write_text(
                        json.dumps({"agentsignore": ignore_name}), encoding="utf-8"
                    )

                apply_code, apply_output = run_main(root, "--apply")
                check_code, check_output = run_main(root, "--check", "--no-diff")

                self.assertEqual(apply_code, 0, apply_output)
                self.assertEqual(check_code, 0, check_output)
                report_labels = [line[:8].strip() for line in check_output.splitlines()]
                self.assertNotIn("CREATE", report_labels)
                self.assertNotIn("UPDATE", report_labels)


if __name__ == "__main__":
    unittest.main()
