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
        self.assertEqual(payload["embedding_model"], "BAAI/bge-m3@BAAI")
        self.assertEqual(payload["chunk_method"], "naive")
        self.assertNotIn("id", payload)
        self.assertNotIn("document_count", payload)

    def test_skips_display_only_embedding_model(self) -> None:
        payload = build_dataset_create_payload(
            {
                "embedding_model": "BAAI/bge-small-en-v1.5",
                "permission": "me",
                "chunk_method": "naive",
            },
            "seafile__library__abc12345",
        )
        self.assertNotIn("embedding_model", payload)
        self.assertEqual(payload["permission"], "me")

    def test_sanitizes_naive_parser_config_runtime_fields(self) -> None:
        payload = build_dataset_create_payload(
            {
                "chunk_method": "naive",
                "parser_config": {
                    "chunk_token_num": 512,
                    "delimiter": "\n",
                    "children_delimiter": "",
                    "filename_embd_weight": 0.1,
                    "image_context_size": 0,
                    "llm_id": "",
                    "pages": [[1, 1000000]],
                    "table_context_size": 0,
                    "topn_tags": 3,
                    "graphrag": {
                        "use_graphrag": False,
                        "batch_chunk_token_size": 4096,
                    },
                    "parent_child": {"use_parent_child": False, "children_delimiter": "\n"},
                },
            },
            "seafile__library__abc12345",
        )
        self.assertEqual(
            payload["parser_config"],
            {
                "chunk_token_num": 512,
                "delimiter": "\n",
                "filename_embd_weight": 0.1,
                "pages": [[1, 1000000]],
                "topn_tags": 3,
                "graphrag": {"use_graphrag": False},
                "parent_child": {"use_parent_child": False, "children_delimiter": "\n"},
            },
        )

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
