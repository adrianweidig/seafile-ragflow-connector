from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from seafile_ragflow_connector.demo.recording import (
    DemoRecordingNames,
    OBSWebhookConfig,
    build_recording_steps,
    write_demo_markdown,
    write_recording_summary,
)


class DemoRecordingTests(unittest.TestCase):
    def test_builds_stable_demo_names(self) -> None:
        names = DemoRecordingNames.build("run 42/test")

        self.assertEqual(names.demo_id, "run-42-test")
        self.assertIn("Demo RAGFlow OpenWebUI Bibliothek run-42-test", names.library_name)
        self.assertIn("Demo Dataset Seafile Sync run-42-test", names.dataset_label)
        self.assertIn("Demo Chat Seafile RAG run-42-test", names.chat_label)
        self.assertEqual(names.file_name, "seafile-ragflow-openwebui-demo-run-42-test.md")
        self.assertIn("DEMO_SEAFILE_RAGFLOW_OPENWEBUI_RUN-42-TEST", names.marker)

    def test_demo_markdown_contains_question_and_marker(self) -> None:
        names = DemoRecordingNames.build("20260602T120000Z")
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / names.file_name
            write_demo_markdown(target, names)

            content = target.read_text(encoding="utf-8")
            self.assertIn(names.marker, content)
            self.assertIn(names.question, content)
            self.assertIn("Seafile bleibt die Quelle der Wahrheit", content)

    def test_recording_steps_cover_required_flow(self) -> None:
        names = DemoRecordingNames.build("flow")
        step_ids = [step["id"] for step in build_recording_steps(names)]

        self.assertEqual(step_ids[0], "obs-start")
        self.assertIn("seafile-library", step_ids)
        self.assertIn("ragflow-dataset", step_ids)
        self.assertIn("ragflow-chat", step_ids)
        self.assertIn("seafile-upload", step_ids)
        self.assertIn("ragflow-chunks", step_ids)
        self.assertIn("openwebui-question", step_ids)
        self.assertEqual(step_ids[-1], "obs-stop")

    def test_obs_config_from_env_redacts_token(self) -> None:
        config = OBSWebhookConfig.from_env(
            {
                "OBS_WEBHOOK_START_URL": "http://127.0.0.1:9900/start",
                "OBS_WEBHOOK_STOP_URL": "http://127.0.0.1:9900/stop",
                "OBS_WEBHOOK_TOKEN": "secret-token",
                "OBS_WEBHOOK_TOKEN_HEADER": "X-OBS-Token",
                "OBS_WEBHOOK_PAYLOAD_MODE": "none",
            }
        )

        self.assertEqual(config.missing_required_actions(), [])
        self.assertEqual(config.headers(), {"X-OBS-Token": "secret-token"})
        redacted = config.redacted()
        self.assertTrue(redacted["token_configured"])
        self.assertNotIn("secret-token", str(redacted))
        self.assertEqual(redacted["payload_mode"], "none")

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


if __name__ == "__main__":
    unittest.main()
