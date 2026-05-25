from __future__ import annotations

import unittest

from seafile_ragflow_connector.openwebui.artifacts import (
    DatasetArtifactInputs,
    build_pipe_spec,
    build_tool_spec,
)


class OpenWebUIArtifactTests(unittest.TestCase):
    def test_tool_and_pipe_specs_are_deterministic_and_secret_free(self) -> None:
        inputs = DatasetArtifactInputs(
            namespace="ragflow",
            repo_id="repo-1",
            dataset_id="dataset-1234567890",
            dataset_name="Demo Library",
            ragflow_chat_id="chat-1",
            proxy_base_url="http://connector:8080",
        )

        tool = build_tool_spec(inputs)
        pipe = build_pipe_spec(inputs)
        tool_again = build_tool_spec(inputs)

        self.assertEqual(tool.definition_hash, tool_again.definition_hash)
        self.assertIn("ragflow_tool_demo_library", tool.artifact_id)
        self.assertIn("ragflow_pipe_demo_library", pipe.artifact_id)
        self.assertEqual(tool.valves["ARTIFACT_ID"], tool.artifact_id)
        self.assertEqual(pipe.valves["ARTIFACT_ID"], pipe.artifact_id)
        self.assertEqual(tool.valves["DATASET_ID"], "dataset-1234567890")
        self.assertEqual(pipe.valves["RAGFLOW_CHAT_ID"], "chat-1")
        self.assertTrue(tool.valves["CONNECTOR_PROXY_VERIFY_SSL"])
        self.assertEqual(tool.valves["CONNECTOR_PROXY_CA_BUNDLE"], "")
        self.assertIn("owner: seafile-ragflow-connector", tool.content)
        self.assertIn("artifact_version: 11", tool.content)
        self.assertIn("artifact_version: 11", pipe.content)
        self.assertFalse(tool.valves["TLS_DEBUG"])
        self.assertEqual(tool.valves["SHOW_SOURCE_SCORES"], True)
        self.assertEqual(tool.valves["LANGUAGE"], "de")
        self.assertEqual(pipe.valves["SOURCE_MARKDOWN_MODE"], "compact")
        self.assertIn("verify = _httpx_verify(", tool.content)
        self.assertIn("class SourceHit(BaseModel):", pipe.content)
        self.assertIn("_normalize_sources(", pipe.content)
        self.assertIn("_TEXT = {", pipe.content)
        self.assertIn("sources.basis", pipe.content)
        self.assertIn("sources.evidence", pipe.content)
        self.assertNotIn("<br>", tool.content)
        self.assertNotIn("<br>", pipe.content)
        self.assertNotIn("proxy-secret", tool.content.lower())
        self.assertNotIn("proxy-secret", str(pipe.payload).lower())
        compile(tool.content, "<openwebui-tool>", "exec")
        compile(pipe.content, "<openwebui-pipe>", "exec")

    def test_pipe_handles_openwebui_background_tasks_locally(self) -> None:
        inputs = DatasetArtifactInputs(
            namespace="ragflow",
            repo_id="repo-1",
            dataset_id="dataset-1234567890",
            dataset_name="Demo Library",
            ragflow_chat_id="chat-1",
            proxy_base_url="http://connector:8080",
        )

        pipe = build_pipe_spec(inputs)

        self.assertIn("__task__: str | None = None", pipe.content)
        self.assertIn("if task:", pipe.content)
        self.assertIn("return _task_response(task, __task_body__ or body)", pipe.content)
        self.assertIn('"model": body.get("model") or self.valves.MODEL_ID or "model"', pipe.content)
        self.assertIn("except httpx.TimeoutException as exc:", pipe.content)
        self.assertIn('"title" in task', pipe.content)
        self.assertIn('return "[]"', pipe.content)

    def test_artifact_metadata_can_be_generated_in_english(self) -> None:
        inputs = DatasetArtifactInputs(
            namespace="ragflow",
            repo_id="repo-1",
            dataset_id="dataset-1234567890",
            dataset_name="Demo Library",
            ragflow_chat_id="chat-1",
            proxy_base_url="http://connector:8080",
            language="en",
        )

        tool = build_tool_spec(inputs)
        pipe = build_pipe_spec(inputs)

        self.assertIn("RAGFlow search", tool.name)
        self.assertIn("Dataset-specific RAGFlow search", str(tool.payload))
        self.assertIn("RAGFlow model", str(pipe.payload))
        self.assertEqual(pipe.valves["LANGUAGE"], "en")

    def test_artifact_metadata_and_embedded_messages_support_product_languages(self) -> None:
        examples = {
            "es": "Búsqueda RAGFlow",
            "fr": "Recherche RAGFlow",
            "pl": "Wyszukiwanie RAGFlow",
            "zh": "RAGFlow 搜索",
            "ar": "بحث RAGFlow",
        }
        for language, expected_name in examples.items():
            with self.subTest(language=language):
                inputs = DatasetArtifactInputs(
                    namespace="ragflow",
                    repo_id="repo-1",
                    dataset_id="dataset-1234567890",
                    dataset_name="Demo Library",
                    ragflow_chat_id="chat-1",
                    proxy_base_url="http://connector:8080",
                    language=language,
                )

                tool = build_tool_spec(inputs)
                pipe = build_pipe_spec(inputs)

                self.assertIn(expected_name, tool.name)
                self.assertEqual(tool.valves["LANGUAGE"], language)
                self.assertEqual(pipe.valves["LANGUAGE"], language)
                self.assertEqual(tool.payload["meta"]["manifest"]["language"], language)
                self.assertIn(language, tool.content)


if __name__ == "__main__":
    unittest.main()
