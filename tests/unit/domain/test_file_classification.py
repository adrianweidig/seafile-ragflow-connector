from __future__ import annotations

import unittest

from seafile_ragflow_connector.domain.file_classification import FilePolicy, classify_file


class FileClassificationTests(unittest.TestCase):
    def test_ada_files_are_text_projected(self) -> None:
        result = classify_file("/src/main.ada", b"procedure Main is\nbegin\n null;\nend Main;\n")
        self.assertTrue(result.should_ingest)
        self.assertTrue(result.is_text)
        self.assertEqual(result.source_extension, ".ada")
        self.assertEqual(result.ingestion_strategy, "text_projection")

    def test_unknown_utf8_file_is_accepted_when_enabled(self) -> None:
        result = classify_file("/custom/domain.filetype", "hello äöü".encode())
        self.assertTrue(result.should_ingest)
        self.assertEqual(result.ingestion_strategy, "text_projection")

    def test_unknown_binary_file_is_skipped(self) -> None:
        result = classify_file("/custom/blob.bin", b"\x00\x01\x02binary")
        self.assertFalse(result.should_ingest)
        self.assertEqual(result.reason, "unknown_binary_or_disallowed")

    def test_deny_extension_wins(self) -> None:
        result = classify_file("/tmp/run.exe", b"plain text")
        self.assertFalse(result.should_ingest)
        self.assertEqual(result.reason, "extension_denied")

    def test_allow_extensions_can_be_strict(self) -> None:
        policy = FilePolicy(allow_extensions=frozenset({".md"}))
        result = classify_file("/src/main.ada", b"procedure Main is null;", policy)
        self.assertFalse(result.should_ingest)
        self.assertEqual(result.reason, "extension_not_allowed")


if __name__ == "__main__":
    unittest.main()
