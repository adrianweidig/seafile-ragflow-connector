from __future__ import annotations

import unittest

from seafile_ragflow_connector.services.file_classification import classify_file
from seafile_ragflow_connector.services.ingestion_artifacts import prepare_ingestion_artifact


class IngestionArtifactTests(unittest.TestCase):
    def test_text_projection_preserves_source_path(self) -> None:
        classification = classify_file("/src/main.adb", b"procedure Main is null;")
        artifact = prepare_ingestion_artifact(classification, b"procedure Main is null;")
        self.assertTrue(artifact.document_name.endswith("__main.adb.txt"))
        self.assertEqual(artifact.mime_type, "text/plain")
        self.assertIn(b"Source path: /src/main.adb", artifact.content)
        self.assertEqual(artifact.metadata["source_path"], "/src/main.adb")


if __name__ == "__main__":
    unittest.main()

