from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "record_real_chrome_demo.py"


class RecordRealChromeDemoCliTests(unittest.TestCase):
    def test_check_tools_reports_expected_keys(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo-root", str(REPO_ROOT), "--check-tools"],
            check=False,
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )

        self.assertIn(completed.returncode, {0, 1})
        self.assertTrue(completed.stdout, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertIn("commands", report)
        self.assertIn("demo_python_dependencies", report)
        self.assertIn("ffmpeg", report["commands"])
        self.assertIn("ffprobe", report["commands"])
