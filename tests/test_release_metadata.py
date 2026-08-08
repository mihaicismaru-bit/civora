import re
import unittest
from pathlib import Path

import civora


class ReleaseMetadataTests(unittest.TestCase):
    def test_runtime_version_matches_pyproject_version(self):
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        self.assertIsNotNone(match, "pyproject.toml must declare a project version")
        self.assertEqual(civora.__version__, match.group(1))

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


if __name__ == "__main__":
    unittest.main()
