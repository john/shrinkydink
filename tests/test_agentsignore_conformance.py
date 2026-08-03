from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "assets" / "runtime"
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "agentsignore" / "v1"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "shrinkydink.py"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import agentsignore


class AgentsIgnoreConformanceTests(unittest.TestCase):
    def test_packaged_conformance_fixtures_pass(self) -> None:
        report = agentsignore.run_conformance(FIXTURE_ROOT)

        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["failed"], 0)
        self.assertGreaterEqual(report["passed"], 30)
        self.assertEqual(
            [suite["name"] for suite in report["suites"]],
            ["canonical-syntax", "docker-agent-compatibility"],
        )

    def test_directory_kind_and_excluded_parent_semantics(self) -> None:
        matcher = agentsignore.AgentsIgnoreMatcher.from_text(
            "build/\nparent/\n!parent/child.txt\nworking/*\n!working/child.txt\n"
        )

        self.assertFalse(matcher.match("build", agentsignore.PATH_FILE).ignored)
        self.assertTrue(matcher.match("build", agentsignore.PATH_DIRECTORY).ignored)
        self.assertTrue(matcher.match("build/output.bin", agentsignore.PATH_FILE).ignored)
        self.assertTrue(matcher.match("parent/child.txt", agentsignore.PATH_FILE).ignored)
        self.assertFalse(matcher.match("working/child.txt", agentsignore.PATH_FILE).ignored)

        typed_negation = agentsignore.AgentsIgnoreMatcher.from_text("same\n!same/\n")
        self.assertTrue(typed_negation.match("same", agentsignore.PATH_FILE).ignored)
        self.assertFalse(
            typed_negation.match("same", agentsignore.PATH_DIRECTORY).ignored
        )
        self.assertEqual(len(typed_negation.active_ignore_rules), 1)

    def test_double_star_is_cross_component_only_as_a_complete_component(self) -> None:
        matcher = agentsignore.AgentsIgnoreMatcher.from_text(
            "docs/**/draft.md\nfoo**bar\n"
        )
        self.assertTrue(matcher.match("docs/draft.md").ignored)
        self.assertTrue(matcher.match("docs/a/b/draft.md").ignored)
        self.assertTrue(matcher.match("fooxbar").ignored)
        self.assertFalse(matcher.match("foo/x/bar").ignored)

    def test_normalization_is_cwd_separator_and_symlink_aware(self) -> None:
        matcher = agentsignore.AgentsIgnoreMatcher.from_text("private.pem\n")
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "src").mkdir()
            root_spelling = matcher.normalize("src\\private.pem", root, root)
            nested_spelling = matcher.normalize("private.pem", root, root / "src")
            dot_spelling = matcher.normalize("src/./private.pem", root, root)
            invalid_spelling = matcher.normalize("invalid\x00path", root, root)
            outside_spelling = matcher.normalize(str(root.parent / "outside.txt"), root, root)

            self.assertEqual(root_spelling.relative, "src/private.pem")
            self.assertEqual(nested_spelling.relative, "src/private.pem")
            self.assertEqual(dot_spelling.relative, "src/private.pem")
            self.assertEqual(invalid_spelling.state, "invalid")
            self.assertEqual(outside_spelling.state, "outside")

            if hasattr(os, "symlink"):
                try:
                    (root / "inside").symlink_to(root / "src", target_is_directory=True)
                    (root / "outside").symlink_to(Path(outside), target_is_directory=True)
                except OSError as exc:
                    self.skipTest(f"symbolic links are unavailable: {exc}")
                inside = matcher.normalize("inside/private.pem", root, root)
                rejected = matcher.normalize("outside/private.pem", root, root)
                self.assertEqual(inside.relative, "src/private.pem")
                self.assertEqual(rejected.state, "outside")

    def test_fixture_mismatch_and_malformed_fixture_have_distinct_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "v1"
            shutil.copytree(FIXTURE_ROOT, copied)
            manifest_path = copied / "expected.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["cases"][0]["expected"] = "excluded"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            mismatch = agentsignore.run_conformance(copied)
            self.assertEqual(mismatch["status"], "fail")
            self.assertEqual(agentsignore.conformance_exit_code(mismatch), 1)

            (copied / "tree.json").write_text("not json", encoding="utf-8")
            malformed = agentsignore.run_conformance(copied)
            self.assertEqual(malformed["status"], "error")
            self.assertEqual(agentsignore.conformance_exit_code(malformed), 2)

    def test_cli_text_and_json_work_outside_a_repository_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            text_result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--check-agentsignore-conformance"],
                cwd=cwd,
                text=True,
                capture_output=True,
                check=False,
            )
            json_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--check-agentsignore-conformance",
                    "--json",
                ],
                cwd=cwd,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(text_result.returncode, 0, text_result.stderr)
            self.assertIn("Agentsignore conformance: PASS", text_result.stdout)
            self.assertEqual(json_result.returncode, 0, json_result.stderr)
            payload = json.loads(json_result.stdout)
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["failed"], 0)
            self.assertEqual(list(cwd.iterdir()), [])

    def test_cli_rejects_repository_mutation_options(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--check-agentsignore-conformance",
                "--ignore-mode",
                "deny",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be combined", result.stderr)


if __name__ == "__main__":
    unittest.main()
