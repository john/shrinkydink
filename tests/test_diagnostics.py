from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_shrinkydink import PROJECT_ROOT, run_main, shrinkydink


FIXTURE = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "diagnostics" / "v1" / "scenarios.json").read_text(
        encoding="utf-8"
    )
)


def init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)


def track(root: Path, relative: str, content: bytes = b"fixture") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    subprocess.run(["git", "-C", str(root), "add", "--", relative], check=True)


class DiagnosticsTests(unittest.TestCase):
    def test_no_ecosystem_agentsignore_has_only_high_confidence_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_git(root)
            detections = shrinkydink.detect_ecosystems(root)
            body = shrinkydink.agentsignore_body(detections)

            self.assertEqual(detections, [])
            self.assertIn(".git/", body)
            self.assertIn(".env.*", body)
            for rule in FIXTURE["ambiguous_rules"]:
                self.assertNotIn(f"\n{rule}\n", f"\n{body}\n")

    def test_ecosystem_rules_are_gated_and_report_every_marker(self) -> None:
        for ecosystem, scenario in FIXTURE["ecosystems"].items():
            with self.subTest(ecosystem=ecosystem), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                marker = root / scenario["marker"]
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("", encoding="utf-8")

                detections = shrinkydink.detect_ecosystems(root)
                by_name = {item.name: item for item in detections}
                body = shrinkydink.agentsignore_body(detections)

                self.assertEqual(set(by_name), {ecosystem})
                self.assertEqual(by_name[ecosystem].markers, (scenario["marker"],))
                self.assertIn(scenario["agent_rule"], body)
                self.assertIn(scenario["marker"], body)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "packages" / "app").mkdir(parents=True)
            (root / "packages" / "app" / "yarn.lock").write_text("", encoding="utf-8")
            node = next(item for item in shrinkydink.detect_ecosystems(root) if item.name == "node")
            self.assertEqual(node.markers, ("package.json", "packages/app/yarn.lock"))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unusual = root / "bad\nrule.tf"
            unusual.write_text("", encoding="utf-8")
            body = shrinkydink.agentsignore_body(shrinkydink.detect_ecosystems(root))
            self.assertIn('"bad\\nrule.tf"', body)
            self.assertNotIn("bad\nrule.tf", body)

    def test_tracked_candidates_become_exact_non_mutating_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_git(root)
            for relative in FIXTURE["tracked_candidates"][:-1]:
                track(root, relative)
            track(root, FIXTURE["tracked_candidates"][-1], b"x" * 2048)

            code, output = run_main(
                root, "--json", "--no-claude", "--no-codex", "--large-file-warning-kb", "1"
            )
            report = json.loads(output)
            by_path = {item["path"]: item for item in report["recommendations"]}
            agentsignore = next(
                change for change in report["changes"] if change["path"] == ".agentsignore"
            )

            self.assertEqual(code, 0, output)
            self.assertEqual(list(by_path), sorted(FIXTURE["tracked_candidates"]))
            for relative in FIXTURE["tracked_candidates"]:
                self.assertEqual(by_path[relative]["suggested_rule"], f"/{relative}")
                self.assertIsNotNone(by_path[relative]["size_bytes"])
                self.assertNotIn(f"\n/{relative}\n", agentsignore["new"])
            self.assertFalse((root / ".agentsignore").exists())

    def test_tracked_secret_warning_never_reads_or_prints_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_git(root)
            secret = root / ".env.production"
            sentinel = "SENTINEL_CREDENTIAL_VALUE"
            track(root, secret.name, sentinel.encode())
            real_read_text = shrinkydink.read_text

            def guarded_read(path: Path) -> str:
                if path == secret:
                    raise AssertionError("candidate content was read")
                return real_read_text(path)

            with mock.patch.object(shrinkydink, "read_text", side_effect=guarded_read):
                code, output = run_main(root, "--json", "--no-claude", "--no-codex")
                text_code, text_output = run_main(root, "--no-claude", "--no-codex", "--no-diff")
            report = json.loads(output)
            warning = next(
                item for item in report["warnings"] if item["kind"] == "tracked-secret-like-path"
            )

            self.assertEqual(code, 0, output)
            self.assertEqual(warning["severity"], "high")
            self.assertIn("does not untrack", warning["message"])
            self.assertIn("rotate", warning["message"])
            self.assertNotIn(sentinel, output)
            self.assertEqual(text_code, 0, text_output)
            self.assertIn("high:tracked-secret-like-path", text_output)
            self.assertIn("Recommendations:", text_output)
            self.assertNotIn(sentinel, text_output)

    def test_json_schema_is_additive_and_conflicts_are_projected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text(
                "<!-- shrinkydink:start -->\nunterminated\n", encoding="utf-8"
            )

            code, output = run_main(root, "--json", "--no-claude", "--no-codex")
            report = json.loads(output)

            self.assertEqual(code, 0, output)
            self.assertEqual(report["report_version"], 1)
            for legacy in ("repo", "mode", "ecosystems", "settings", "changes", "warnings"):
                self.assertIn(legacy, report)
            for additive in ("ecosystem_detections", "default_rule_groups", "conflicts", "recommendations"):
                self.assertIn(additive, report)
            self.assertEqual(
                report["conflicts"],
                [item for item in report["changes"] if item["status"] == "conflict"],
            )
            self.assertTrue(all("severity" in item for item in report["warnings"]))

    def test_report_structure_is_stable_across_audit_check_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_git(root)
            track(root, "data/fixture.db")
            invocations = (
                ((), 0),
                (("--check", "--no-diff"), 1),
                (("--apply",), 0),
                (("--check", "--no-diff"), 0),
            )
            for arguments, expected_code in invocations:
                code, output = run_main(
                    root, *arguments, "--json", "--no-claude", "--no-codex"
                )
                report = json.loads(output)
                self.assertEqual(code, expected_code, output)
                self.assertEqual(report["report_version"], 1)
                self.assertIsInstance(report["changes"], list)
                self.assertIsInstance(report["conflicts"], list)
                self.assertIsInstance(report["warnings"], list)
                self.assertIsInstance(report["recommendations"], list)
                self.assertEqual(report["recommendations"][0]["path"], "data/fixture.db")

    def test_exact_recommendation_rules_escape_gitignore_metacharacters(self) -> None:
        self.assertEqual(
            shrinkydink.exact_ignore_rule("fixtures/a[b]*?.db"),
            "/fixtures/a\\[b\\]\\*\\?.db",
        )
        self.assertEqual(shrinkydink.exact_ignore_rule("fixtures/trailing  "), "/fixtures/trailing\\ \\ ")
        self.assertIsNone(shrinkydink.exact_ignore_rule("fixtures/line\nbreak.db"))

    def test_user_rules_keep_precedence_and_apply_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_git(root)
            originals = {
                ".gitignore": "!dist/\n",
                ".gitattributes": "*.md -text\n",
                ".agentsignore": "!fixtures/large.dat\n",
            }
            for relative, content in originals.items():
                (root / relative).write_text(content, encoding="utf-8")

            apply_code, apply_output = run_main(root, "--apply", "--no-claude", "--no-codex")
            check_code, check_output = run_main(root, "--check", "--no-diff", "--no-claude", "--no-codex")

            self.assertEqual(apply_code, 0, apply_output)
            self.assertEqual(check_code, 0, check_output)
            for relative, content in originals.items():
                rendered = (root / relative).read_text(encoding="utf-8")
                self.assertTrue(rendered.endswith(content), relative)
                self.assertGreater(rendered.rfind(content.strip()), rendered.find("# shrinkydink:end"))

    def test_established_gitattributes_gets_prominent_policy_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".gitattributes").write_text("*.md -text\n", encoding="utf-8")
            code, output = run_main(root, "--json", "--no-claude", "--no-codex")
            report = json.loads(output)
            warning = next(item for item in report["warnings"] if item["kind"] == "gitattributes-policy")

            self.assertEqual(code, 0, output)
            self.assertEqual(warning["severity"], "high")
            self.assertIn("not LLM access", warning["message"])
            self.assertIn("renormalize", warning["message"])


if __name__ == "__main__":
    unittest.main()
