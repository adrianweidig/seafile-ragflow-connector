from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

from seafile_ragflow_connector import __version__

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "ghcr.io/adrianweidig/seafile-ragflow-connector"


class ReleaseMetadataTest(unittest.TestCase):
    def test_package_versions_match(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(pyproject["project"]["version"], __version__)

    def test_readme_badges_and_changelogs_match_package_version(self) -> None:
        for path in ("README.md", "README.en.md"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn(f"Version {__version__}", text)
            self.assertIn(f"version-{__version__}-informational.svg", text)

        release_heading = re.compile(
            rf"^## {re.escape(__version__)} - \d{{4}}-\d{{2}}-\d{{2}}$",
            re.MULTILINE,
        )
        for path in ("CHANGELOG.md", "CHANGELOG.en.md"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertRegex(text, release_heading)

    def test_operator_image_guidance_mentions_current_release_tag(self) -> None:
        for path in ("README.md", "README.en.md", "connector.env.example"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn(f"{IMAGE}:{__version__}", text)
            self.assertIn("latest", text)
        portainer_env = (ROOT / "deploy" / "portainer" / "stack.env.example").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"seafile-ragflow-connector:{__version__}", portainer_env)

    def test_docker_workflow_keeps_release_image_tags(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "docker.yml").read_text(encoding="utf-8")

        self.assertIn(r"^v([0-9]+)\.([0-9]+)(\.([0-9]+))?$", workflow)
        self.assertIn('echo "type=raw,value=${version}"', workflow)
        self.assertIn('echo "type=raw,value=${minor}"', workflow)
        self.assertIn("${{ steps.release-tags.outputs.tags }}", workflow)
        self.assertIn("type=sha,prefix=sha-", workflow)
        self.assertNotIn("type=semver", workflow)
        self.assertNotIn("type=match", workflow)

    def test_release_process_documents_minor_and_major_release_tags(self) -> None:
        release_process = (ROOT / "docs" / "RELEASE_PROCESS.md").read_text(
            encoding="utf-8"
        )

        for expected in ("v2.1", "v3.0", "v3.0.1"):
            self.assertIn(expected, release_process)
        self.assertIn("ghcr.io/adrianweidig/seafile-ragflow-connector:2.1", release_process)
        self.assertIn("sha-<commit>", release_process)
        self.assertIn("ohne führendes `v`", release_process)
        self.assertIn("Minor-Tag `3.0`", release_process)


if __name__ == "__main__":
    unittest.main()
