from __future__ import annotations

import unittest

from seafile_ragflow_connector.domain.template_payload_builder import (
    TemplateError,
    build_dataset_create_payload,
    dataset_settings_fingerprint,
)


class TemplatePayloadBuilderTests(unittest.TestCase):
    def test_builtin_payload_copies_allowed_fields(self) -> None:
        payload = build_dataset_create_payload(
            {
                "name": "connector_template",
                "id": "runtime",
                "embedding_model": "BAAI/bge-m3@BAAI",
                "permission": "team",
                "chunk_method": "naive",
                "parser_config": {"chunk_token_num": 512},
                "document_count": 99,
            },
            "seafile__library__abc12345",
        )
        self.assertEqual(payload["name"], "seafile__library__abc12345")
        self.assertEqual(payload["chunk_method"], "naive")
        self.assertNotIn("id", payload)
        self.assertNotIn("document_count", payload)

    def test_pipeline_payload_excludes_builtin_fields(self) -> None:
        payload = build_dataset_create_payload(
            {
                "embedding_model": "BAAI/bge-m3@BAAI",
                "permission": "team",
                "parse_type": 2,
                "pipeline_id": "d0bebe30ae2211f0970942010a8e0005",
            },
            "seafile__project__2deffbac",
        )
        self.assertEqual(payload["parse_type"], 2)
        self.assertEqual(payload["pipeline_id"], "d0bebe30ae2211f0970942010a8e0005")
        self.assertNotIn("chunk_method", payload)
        self.assertNotIn("parser_config", payload)

    def test_mixed_mode_fails(self) -> None:
        with self.assertRaises(TemplateError):
            build_dataset_create_payload(
                {
                    "chunk_method": "naive",
                    "parser_config": {},
                    "parse_type": 2,
                    "pipeline_id": "d0bebe30ae2211f0970942010a8e0005",
                },
                "seafile__project__2deffbac",
            )

    def test_invalid_pipeline_id_fails(self) -> None:
        with self.assertRaises(TemplateError):
            build_dataset_create_payload(
                {"parse_type": 2, "pipeline_id": "ABC"},
                "seafile__project__2deffbac",
            )

    def test_dataset_fingerprint_changes_on_settings_change(self) -> None:
        first = dataset_settings_fingerprint({"chunk_method": "naive"})
        second = dataset_settings_fingerprint({"chunk_method": "manual"})
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
