from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

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

    def test_help_includes_clean_overlay_and_passive_capture_options(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            check=True,
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )

        self.assertIn("--overlay-mode", completed.stdout)
        self.assertIn("--passive-duration", completed.stdout)
        self.assertIn("synthetic pointers", completed.stdout)

    def test_overlay_mode_none_keeps_real_frame_unchanged(self) -> None:
        spec = importlib.util.spec_from_file_location("record_real_chrome_demo", SCRIPT)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        if module.Image is None:
            self.skipTest("Pillow is not installed")

        frame = module.Image.new("RGB", (96, 54), (20, 30, 40))
        scene = module.Scene(
            name="Kapitel 1",
            caption="Diese Caption darf im Clean-Modus nicht eingebrannt werden.",
            duration=1.0,
            highlight=(0.1, 0.1, 0.9, 0.9),
            pointer=(0.5, 0.5),
        )

        rendered = module.render_frame(
            frame,
            scene,
            elapsed=0.0,
            scene_elapsed=0.0,
            total_duration=1.0,
            overlay_mode="none",
        )

        self.assertEqual(rendered.mode, "RGB")
        self.assertEqual(rendered.size, frame.size)
        self.assertEqual(rendered.tobytes(), frame.tobytes())

    def test_default_overlay_mode_is_clean(self) -> None:
        spec = importlib.util.spec_from_file_location("record_real_chrome_demo", SCRIPT)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        with mock.patch.object(sys, "argv", [str(SCRIPT)]):
            args = module.parse_args()

        self.assertEqual(args.overlay_mode, "none")

    def test_final_scenes_show_preview_and_original(self) -> None:
        spec = importlib.util.spec_from_file_location("record_real_chrome_demo", SCRIPT)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        scene_names = [scene.name for scene in module.scenes()]
        self.assertIn("Kapitel 13: Connector-Preview", scene_names)
        self.assertIn("Kapitel 14: Original in Seafile", scene_names)
        self.assertIn("Kapitel 15: Abschlusskontrolle", scene_names)

        preview_scene = next(
            scene for scene in module.scenes() if "Connector-Preview" in scene.name
        )
        original_scene = next(
            scene for scene in module.scenes() if "Original in Seafile" in scene.name
        )
        final_scene = next(
            scene for scene in module.scenes() if "Abschlusskontrolle" in scene.name
        )

        self.assertIn("sources\\/preview", preview_scene.js)
        self.assertIn("seafile\\.top\\.secret", original_scene.js)
        self.assertGreaterEqual(final_scene.wait_after_action, 7.0)

    def test_only_ragflow_scenes_dismiss_chrome_popups(self) -> None:
        spec = importlib.util.spec_from_file_location("record_real_chrome_demo", SCRIPT)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        dismissing = [
            scene.name for scene in module.scenes() if scene.dismiss_chrome_popups
        ]

        self.assertEqual(
            dismissing,
            ["Kapitel 9: RAGFlow-Ergebnis", "Kapitel 10: RAGFlow-Chat"],
        )
