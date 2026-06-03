from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from seafile_ragflow_connector.demo.recording import (
    DemoRecordingNames,
    OBSWebhookConfig,
    build_recording_steps,
    validate_recording_artifact,
    write_demo_markdown,
    write_recording_summary,
)


class DemoRecordingTests(unittest.TestCase):
    def test_builds_stable_demo_names(self) -> None:
        names = DemoRecordingNames.build("run 42/test")

        self.assertEqual(names.demo_id, "run-42-test")
        self.assertIn("Demo OBS Seafile RAGFlow OpenWebUI run-42-test", names.library_name)
        self.assertIn("Demo OBS Dataset Seafile Sync run-42-test", names.dataset_label)
        self.assertIn("Demo OBS Chat Seafile RAG run-42-test", names.chat_label)
        self.assertEqual(
            names.file_name,
            "demo-seafile-ragflow-openwebui-workflow-run-42-test.md",
        )
        self.assertEqual(
            names.recording_name,
            "demo-seafile-ragflow-openwebui-full-workflow-run-42-test",
        )

    def test_demo_markdown_contains_question_and_marker(self) -> None:
        names = DemoRecordingNames.build("20260602T120000Z")
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / names.file_name
            write_demo_markdown(target, names)

            content = target.read_text(encoding="utf-8")
            self.assertIn(names.marker, content)
            self.assertIn(names.question, content)
            self.assertIn("Bibliothek-Sync-Chunk-Preview-Originalprüfung", content)
            self.assertIn("Die Bibliothek ist zunächst leer", content)

    def test_recording_steps_cover_required_flow(self) -> None:
        names = DemoRecordingNames.build("flow")
        step_ids = [step["id"] for step in build_recording_steps(names)]

        self.assertEqual(step_ids[0], "browser-prepare")
        self.assertIn("obs-start", step_ids)
        self.assertIn("seafile-library-create", step_ids)
        self.assertIn("seafile-library-empty", step_ids)
        self.assertIn("ragflow-dataset-create", step_ids)
        self.assertIn("ragflow-chat-create", step_ids)
        self.assertIn("seafile-upload", step_ids)
        self.assertIn("ragflow-sync", step_ids)
        self.assertIn("ragflow-parse", step_ids)
        self.assertIn("ragflow-chunks", step_ids)
        self.assertIn("openwebui-question", step_ids)
        self.assertIn("openwebui-preview", step_ids)
        self.assertIn("openwebui-original", step_ids)
        self.assertEqual(step_ids[-1], "obs-stop")

    def test_obs_config_from_env_redacts_token(self) -> None:
        config = OBSWebhookConfig.from_env(
            {
                "OBS_WEBHOOK_START_URL": "http://127.0.0.1:9900/start",
                "OBS_WEBHOOK_STOP_URL": "http://127.0.0.1:9900/stop",
                "OBS_WEBHOOK_TOKEN": "secret-token",
                "OBS_WEBHOOK_TOKEN_HEADER": "X-OBS-Token",
                "OBS_WEBHOOK_PAYLOAD_MODE": "none",
                "OBS_RECORDING_OUTPUT_DIR": "/recordings",
                "OBS_RECORDING_FORMAT": "mkv",
            }
        )

        self.assertEqual(config.missing_required_actions(), [])
        self.assertEqual(config.headers(), {"X-OBS-Token": "secret-token"})
        redacted = config.redacted()
        self.assertTrue(redacted["token_configured"])
        self.assertNotIn("secret-token", str(redacted))
        self.assertEqual(redacted["payload_mode"], "none")
        self.assertEqual(redacted["recording_output_dir"], "/recordings")
        self.assertEqual(redacted["expected_extension"], ".mkv")

    def test_recording_summary_contains_no_plain_token(self) -> None:
        names = DemoRecordingNames.build("summary")
        config = OBSWebhookConfig(
            start_url="http://127.0.0.1/start",
            stop_url="http://127.0.0.1/stop",
            token="plain-secret",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "summary.json"
            write_recording_summary(
                target,
                names=names,
                mode="dry-run",
                obs_config=config,
                checks={"ok": True},
            )

            content = target.read_text(encoding="utf-8")
            self.assertIn(names.library_name, content)
            self.assertNotIn("plain-secret", content)

    def test_recording_artifact_requires_non_empty_mkv(self) -> None:
        names = DemoRecordingNames.build("artifact")
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            webm = output_dir / f"{names.recording_name}.webm"
            webm.write_bytes(b"not accepted")

            missing = validate_recording_artifact(
                recording_name=names.recording_name,
                demo_id=names.demo_id,
                output_dir=output_dir,
            )
            self.assertFalse(missing["valid"])

            mkv = output_dir / f"{names.recording_name}.mkv"
            mkv.write_bytes(b"mkv bytes")
            valid = validate_recording_artifact(
                recording_name=names.recording_name,
                demo_id=names.demo_id,
                output_dir=output_dir,
            )
            self.assertTrue(valid["valid"])
            self.assertEqual(valid["path"], str(mkv))


if __name__ == "__main__":
    unittest.main()
