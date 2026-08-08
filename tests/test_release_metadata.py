import re
import unittest
from pathlib import Path

import civora


class ReleaseMetadataTests(unittest.TestCase):
    def _project_version(self) -> str:
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        self.assertIsNotNone(match, "pyproject.toml must declare a project version")
        return match.group(1)

    def test_runtime_version_matches_pyproject_version(self):
        self.assertEqual(civora.__version__, self._project_version())

    def test_declared_python_lower_bound_is_explicit(self):
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        self.assertIsNotNone(
            re.search(r'^requires-python\s*=\s*">=3\.10"', pyproject, re.MULTILINE),
            "declared Python lower bound must remain explicit until release policy changes",
        )

    def test_readme_declares_release_closure_mode(self):
        readme = Path("README.md").read_text(encoding="utf-8")
        self.assertIn("v1.0 release-closure mode", readme)
        self.assertNotIn(
            "more recent conversational checkpoints remain to be consolidated",
            readme.casefold(),
        )

    def test_changelog_contains_declared_release_version(self):
        changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
        version = re.escape(self._project_version())
        self.assertIsNotNone(
            re.search(rf'^## \[{version}\](?:\s+-\s+\d{{4}}-\d{{2}}-\d{{2}})?\s*$', changelog, re.MULTILINE),
            "CHANGELOG must contain a release section matching the declared package version",
        )


if __name__ == "__main__":
    unittest.main()
