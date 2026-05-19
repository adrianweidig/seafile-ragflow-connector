from __future__ import annotations

import unittest

from seafile_ragflow_connector.domain.file_classification import classify_file
from seafile_ragflow_connector.domain.ingestion_artifacts import prepare_ingestion_artifact


class IngestionArtifactTests(unittest.TestCase):
    def test_text_projection_preserves_source_path(self) -> None:
        classification = classify_file("/src/main.adb", b"procedure Main is null;")
        artifact = prepare_ingestion_artifact(classification, b"procedure Main is null;")
        self.assertTrue(artifact.document_name.endswith("__main.adb.txt"))
        self.assertEqual(artifact.mime_type, "text/plain")
        self.assertIn(b"Source path: /src/main.adb", artifact.content)
        self.assertEqual(artifact.metadata["source_path"], "/src/main.adb")

    def test_text_projection_hashes_are_deterministic(self) -> None:
        data = b"procedure Main is null;"
        classification = classify_file("/src/main.ads", data)
        first = prepare_ingestion_artifact(classification, data)
        second = prepare_ingestion_artifact(classification, data)
        self.assertEqual(first.source_content_sha256, second.source_content_sha256)
        self.assertEqual(first.ingested_content_sha256, second.ingested_content_sha256)
        self.assertEqual(first.document_name, second.document_name)


if __name__ == "__main__":
    unittest.main()
