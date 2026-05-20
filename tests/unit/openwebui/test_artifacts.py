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
        self.assertIn("owner: seafile-ragflow-connector", tool.content)
        self.assertNotIn("proxy-secret", tool.content.lower())
        self.assertNotIn("proxy-secret", str(pipe.payload).lower())


if __name__ == "__main__":
    unittest.main()
