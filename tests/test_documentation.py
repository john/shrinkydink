from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_shrinkydink import PROJECT_ROOT, run_main


EXAMPLES = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "documentation" / "v1" / "examples.json").read_text(
        encoding="utf-8"
    )
)


class DocumentationTests(unittest.TestCase):
    def test_readme_has_required_contract_and_canonical_commands(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        for heading in (
            "## Install",
            "## Audit, apply, and check",
            "## Automatic defaults and ecosystem detection",
            "## Diagnostics and JSON reports",
            "## Upgrade",
        ):
            self.assertIn(heading, readme)
        for term in (
            "automatic defaults",
            "recommendations",
            "warnings",
            "denials",
            "shared configuration",
            "local configuration",
            "not a sandbox",
        ):
            self.assertIn(term, readme.lower())
        for command in EXAMPLES["canonical_commands"]:
            self.assertIn(command, readme)

    def test_documentation_scenarios_execute(self) -> None:
        for scenario, commands in EXAMPLES["scenarios"].items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                subprocess.run(["git", "init", "-q", str(root)], check=True)
                if scenario == "established":
                    (root / ".gitignore").write_text("!dist/\n", encoding="utf-8")
                    (root / ".gitattributes").write_text("*.md -text\n", encoding="utf-8")
                elif scenario == "large_fixture":
                    fixture = root / "fixtures" / "large.dat"
                    fixture.parent.mkdir()
                    fixture.write_bytes(b"x" * 2048)
                    subprocess.run(
                        ["git", "-C", str(root), "add", "--", "fixtures/large.dat"], check=True
                    )
                elif scenario == "upgrade":
                    (root / ".agentsignore").write_text(
                        "# shrinkydink:start\n"
                        "# Dependencies, caches, build products, and coverage\n"
                        "vendor/\nout/\n*.db\n*.map\n*.bin\n"
                        "# shrinkydink:end\n\n"
                        "!fixtures/large.dat\n",
                        encoding="utf-8",
                    )

                outputs = []
                for arguments in commands:
                    code, output = run_main(root, *arguments, "--no-claude", "--no-codex")
                    outputs.append(output)
                    self.assertEqual(code, 0, output)

                if scenario == "established":
                    self.assertIn("gitattributes-policy", outputs[0])
                    self.assertTrue((root / ".gitignore").read_text(encoding="utf-8").endswith("!dist/\n"))
                elif scenario == "large_fixture":
                    report = json.loads(outputs[0])
                    recommendation = next(
                        item for item in report["recommendations"] if item["path"] == "fixtures/large.dat"
                    )
                    self.assertEqual(recommendation["suggested_rule"], "/fixtures/large.dat")
                    self.assertFalse((root / ".agentsignore").exists())
                elif scenario == "upgrade":
                    self.assertIn("agentsignore-policy-upgrade", outputs[0])
                    self.assertTrue(
                        (root / ".agentsignore")
                        .read_text(encoding="utf-8")
                        .endswith("!fixtures/large.dat\n")
                    )

    def test_internal_markdown_links_exist(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        for relative in (
            "references/configuration.md",
            "references/installation.md",
            "references/platform-support.md",
            "references/agentsignore.md",
        ):
            self.assertIn(f"]({relative})", readme)
            self.assertTrue((PROJECT_ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
