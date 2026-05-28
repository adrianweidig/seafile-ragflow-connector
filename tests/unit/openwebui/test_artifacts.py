from __future__ import annotations

import json
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
        self.assertIn("artifact_version: 19", tool.content)
        self.assertIn("artifact_version: 19", pipe.content)
        self.assertFalse(tool.valves["TLS_DEBUG"])
        self.assertEqual(tool.valves["SHOW_SOURCE_SCORES"], True)
        self.assertEqual(tool.valves["LANGUAGE"], "de")
        self.assertEqual(pipe.name, "Seafile · Demo Library")
        self.assertEqual(pipe.valves["MODEL_NAME"], "Seafile · Demo Library")
        self.assertEqual(pipe.valves["SOURCE_MARKDOWN_MODE"], "audit")
        self.assertEqual(pipe.valves["RETRIEVAL_ONLY_FALLBACK"], "brief")
        self.assertEqual(pipe.valves["EMIT_CITATION_EVENTS"], True)
        self.assertEqual(pipe.valves["APPEND_SOURCE_OVERVIEW"], True)
        self.assertEqual(pipe.valves["SHOW_SOURCE_SCORES"], False)
        self.assertEqual(pipe.valves["SHOW_LOCATOR_QUALITY"], True)
        self.assertEqual(pipe.valves["REQUEST_TIMEOUT_SECONDS"], 180.0)
        self.assertEqual(pipe.valves["ANSWER_SYNTHESIS_MAX_TOKENS"], 700)
        self.assertEqual(pipe.valves["ENABLE_ANSWER_SYNTHESIS_FALLBACK"], False)
        self.assertEqual(pipe.valves["ANSWER_LLM_BASE_URL"], "")
        self.assertEqual(pipe.valves["ANSWER_LLM_MODEL"], "")
        self.assertEqual(pipe.valves["ANSWER_LLM_API_KEY"], "")
        self.assertEqual(pipe.valves["STATUS_MODE"], "minimal")
        self.assertEqual(pipe.valves["HIDE_FINAL_STATUS"], False)
        self.assertEqual(pipe.valves["ALLOW_CONNECTOR_SOURCE_LINKS"], False)
        self.assertIn("verify = _httpx_verify(", tool.content)
        self.assertIn("ssl.create_default_context", tool.content)
        self.assertIn("ssl.create_default_context", pipe.content)
        self.assertIn("class SourceHit:", pipe.content)
        self.assertIn("_normalize_sources(", pipe.content)
        self.assertIn("DEFAULT_RAG_SYSTEM_PROMPT", pipe.content)
        self.assertIn("generate_answer", pipe.content)
        self.assertIn("version: 3.7.0", pipe.content)
        self.assertIn("ANSWER_SYNTHESIS_MAX_TOKENS", pipe.content)
        self.assertIn('"max_tokens": int(valves.ANSWER_SYNTHESIS_MAX_TOKENS)', pipe.content)
        self.assertIn("EMIT_CITATION_EVENTS", pipe.content)
        self.assertIn("ALLOW_CONNECTOR_SOURCE_LINKS", pipe.content)
        self.assertIn("_best_source_url(", pipe.content)
        self.assertNotIn("proxy-secret", tool.content.lower())
        self.assertNotIn("proxy-secret", str(pipe.payload).lower())
        self.assertNotIn("proxy-secret", str(pipe.valves).lower())
        compile(tool.content, "<openwebui-tool>", "exec")
        compile(pipe.content, "<openwebui-pipe>", "exec")

    def test_generated_artifacts_clean_html_snippets_with_parser(self) -> None:
        inputs = DatasetArtifactInputs(
            namespace="ragflow",
            repo_id="repo-1",
            dataset_id="dataset-1234567890",
            dataset_name="Demo Library",
            ragflow_chat_id="chat-1",
            proxy_base_url="http://connector:8080",
        )
        tool_namespace: dict[str, object] = {}
        tool = build_tool_spec(inputs)
        exec(compile(tool.content, "<openwebui-tool>", "exec"), tool_namespace)

        for namespace in (tool_namespace, _pipe_namespace()):
            with self.subTest(namespace="tool" if namespace is tool_namespace else "pipe"):
                cleaner = namespace["_clean_snippet"]
                cleaned = cleaner(
                    "<table><tr><td>Alpha</td><td>&uuml;</td></tr></table>"
                    "<script>hidden()</script>"
                )

                self.assertEqual(cleaned, "Alpha | ü")
                self.assertNotIn("hidden", cleaned)
                self.assertNotIn("<td>", cleaned)

                malformed = (
                    "<style" * 2000
                    + "<table><tr><td>Beta</td><td>&Uuml;ber</td></tr></table>"
                )
                self.assertEqual(cleaner(malformed), "Beta | Über")

    def test_pipe_spec_can_enable_answer_synthesis_without_hashing_api_key(self) -> None:
        inputs = DatasetArtifactInputs(
            namespace="ragflow",
            repo_id="repo-1",
            dataset_id="dataset-1234567890",
            dataset_name="Demo Library",
            ragflow_chat_id="chat-1",
            proxy_base_url="http://connector:8080",
            answer_synthesis_enabled=True,
            answer_llm_base_url="http://litellm:4000/v1",
            answer_llm_model="groq-rag-quality",
        )

        pipe = build_pipe_spec(inputs)

        self.assertTrue(pipe.valves["ENABLE_ANSWER_SYNTHESIS_FALLBACK"])
        self.assertEqual(pipe.valves["ANSWER_LLM_BASE_URL"], "http://litellm:4000/v1")
        self.assertEqual(pipe.valves["ANSWER_LLM_MODEL"], "groq-rag-quality")
        self.assertEqual(pipe.valves["ANSWER_LLM_API_KEY"], "")

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

        self.assertIn("__task__: Optional[str] = None", pipe.content)
        self.assertIn("if task:", pipe.content)
        self.assertIn("return _task_response(task, __task_body__ or body)", pipe.content)
        self.assertIn("or _clean(valves.MODEL_ID)", pipe.content)
        self.assertIn("RAG_ASSISTANT_BEHAVIOR", pipe.content)
        self.assertIn("except httpx.TimeoutException as exc:", pipe.content)
        self.assertIn('"title" in task', pipe.content)
        self.assertIn('return "[]"', pipe.content)

    def test_pipe_template_builds_chat_rag_payload(self) -> None:
        inputs = DatasetArtifactInputs(
            namespace="ragflow",
            repo_id="repo-1",
            dataset_id="dataset-1234567890",
            dataset_name="Demo Library",
            ragflow_chat_id="chat-1",
            proxy_base_url="http://connector:8080",
        )
        pipe = build_pipe_spec(inputs)
        namespace = {}

        exec(compile(pipe.content, "<openwebui-pipe>", "exec"), namespace)
        pipe_instance = namespace["Pipe"]()
        self.assertEqual(pipe_instance.type, "manifold")
        self.assertFalse(pipe_instance.citation)
        pipe_instance.valves.ARTIFACT_ID = pipe.artifact_id
        pipe_instance.valves.CONNECTOR_PROXY_BASE_URL = "http://connector:8080"
        pipe_instance.valves.CONNECTOR_PROXY_SHARED_SECRET = "test-shared-secret"
        pipe_instance.valves.DATASET_ID = "dataset-1234567890"
        pipe_instance.valves.RAGFLOW_CHAT_ID = "chat-1"
        pipe_instance.valves.MODEL_ID = "ragflow/demo_library"
        pipe_instance.valves.SOURCE_MARKDOWN_MODE = str(pipe.valves["SOURCE_MARKDOWN_MODE"])

        self.assertEqual(namespace["_configuration_error"](pipe_instance.valves), "")
        payload = namespace["_build_payload"](
            pipe_instance.valves,
            {"messages": [{"role": "user", "content": "Was steht im Dokument?"}]},
            {"id": "user-1", "email": "user@example.invalid"},
        )

        self.assertEqual(payload["mode"], "chat")
        self.assertEqual(payload["query_mode"], "chat")
        self.assertEqual(payload["response_mode"], "chat")
        self.assertTrue(payload["generate_answer"])
        self.assertTrue(payload["return_sources"])
        self.assertEqual(payload["ragflow"]["mode"], "chat")
        self.assertTrue(payload["openwebui"]["expects_generated_answer"])
        self.assertEqual(payload["openwebui"]["source_markdown_mode"], "audit")
        self.assertEqual(payload["openwebui"]["source_display_mode"], "audit")
        self.assertTrue(payload["openwebui"]["audit_evidence"])
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn("RAG_ASSISTANT_BEHAVIOR", payload["messages"][0]["content"])

    def test_pipe_filters_connector_proxy_links_from_sources(self) -> None:
        namespace = _pipe_namespace()

        sources = namespace["_normalize_sources"](
            [
                {
                    "name": "report.pdf",
                    "url": "http://connector:8080/api/openwebui/proxy/chat?token=abc",
                    "source_metadata": {
                        "preview_url": "https://seafile.local/lib/repo/file/report.pdf",
                        "page": 3,
                    },
                    "text": "Das ist ein belastbarer Dokumentauszug mit genug Inhalt.",
                },
                {
                    "name": "internal-only.md",
                    "preview_url": "http://connector:8080/api/openwebui/proxy/query",
                    "text": "Dieser Treffer hat nur einen internen Backend-Link.",
                },
            ],
            connector_base_url="http://connector:8080",
            allow_connector_source_links=False,
        )

        serialized = json.dumps(sources, ensure_ascii=False)
        self.assertIn("https://seafile.local/lib/repo/file/report.pdf", serialized)
        self.assertNotIn("api/openwebui/proxy", serialized)
        self.assertNotIn("connector:8080", serialized)

    def test_pipe_cleans_source_inventory_fallback_for_non_inventory_questions(self) -> None:
        namespace = _pipe_namespace()
        sources = [
            {
                "name": "connector-live-check.md",
                "text": "Relevanter Inhalt aus dem Markdown-Dokument.",
            },
            {
                "name": "connector-live-check.txt",
                "text": "Relevanter Inhalt aus dem Text-Dokument.",
            },
        ]

        answer = namespace["_postprocess_synthesized_answer"](
            (
                "Die Verfügbaren Quellen sind [Quelle 1] (connector-live-check.md) "
                "und [Quelle 2] (connector-live-check.txt)."
            ),
            sources,
            "Was regelt das Dokument zum mobilen Arbeiten?",
        )

        self.assertEqual(answer, "")

    def test_pipe_final_answer_uses_audit_table_and_native_citations_by_default(self) -> None:
        inputs = DatasetArtifactInputs(
            namespace="ragflow",
            repo_id="repo-1",
            dataset_id="dataset-1234567890",
            dataset_name="Demo Library",
            ragflow_chat_id="chat-1",
            proxy_base_url="http://connector:8080",
        )
        pipe = build_pipe_spec(inputs)
        namespace = _pipe_namespace()
        pipe_instance = namespace["Pipe"]()
        for key, value in pipe.valves.items():
            if key in pipe_instance.valves.__class__.model_fields:
                setattr(pipe_instance.valves, key, value)
        sources = [
            {
                "name": "report.pdf",
                "text": "Der relevante Auszug steht hier.",
                "score": 0.91,
                "source_metadata": {"page": 2},
            }
        ]

        final_answer = namespace["_compose_final_answer"](
            "Mobiles Arbeiten ist im Dokument als geregelter Prozess beschrieben.",
            sources,
            pipe_instance.valves,
        )

        self.assertTrue(final_answer.startswith("Mobiles Arbeiten ist"))
        self.assertIn("[S1]", final_answer)
        self.assertIn("## Nachweise", final_answer)
        self.assertIn(
            "| ID | Gestützte Aussage | Dokument | Fundstelle | Relevanz | Öffnen |",
            final_answer,
        )
        self.assertNotIn("chunk_id", final_answer)
        self.assertNotIn("document_id", final_answer)

    def test_pipe_strips_legacy_appended_source_block_before_rendering_once(self) -> None:
        namespace = _pipe_namespace()
        pipe_instance = namespace["Pipe"]()
        pipe_instance.valves.SOURCE_MARKDOWN_MODE = "audit"
        pipe_instance.valves.APPEND_SOURCE_OVERVIEW = True
        sources = [
            {
                "name": "audit.md",
                "text": "Der Marker steht im Auditdokument.",
                "score": 0.91,
                "source_metadata": {"page": 2},
            }
        ]

        legacy_answer = (
            "Inhaltliche Antwort [S1]\n\n"
            "---\n"
            "## Nachweise\n\n"
            "| ID | Gestützte Aussage | Dokument | Fundstelle | Relevanz | Öffnen |\n"
            "|---|---|---|---|---|---|\n"
            "| S1 | Alt | audit.md | Seite 2 | hoch | Preview öffnen |"
        )
        final_answer = namespace["_compose_final_answer"](
            legacy_answer,
            sources,
            pipe_instance.valves,
        )

        self.assertTrue(final_answer.startswith("Inhaltliche Antwort [S1]"))
        self.assertEqual(final_answer.count("## Nachweise"), 1)
        self.assertIn("Der Marker steht im Auditdokument.", final_answer)

    def test_pipe_treats_source_markdown_only_as_retrieval_only(self) -> None:
        namespace = _pipe_namespace()
        pipe_instance = namespace["Pipe"]()
        pipe_instance.valves.SOURCE_MARKDOWN_MODE = "audit"
        pipe_instance.valves.APPEND_SOURCE_OVERVIEW = True
        pipe_instance.valves.RETRIEVAL_ONLY_FALLBACK = "brief"
        sources = [
            {
                "name": "fallback.md",
                "text": "Nur Retrieval-Treffer.",
                "score": 0.73,
                "source_metadata": {"page": 1},
            }
        ]

        source_only = (
            "## Nachweise\n\n"
            "| ID | Gestützte Aussage | Dokument | Fundstelle | Relevanz | Öffnen |\n"
            "|---|---|---|---|---|---|\n"
            "| S1 | Nur Treffer | fallback.md | Seite 1 | mittel | Preview öffnen |"
        )
        final_answer = namespace["_compose_final_answer"](
            source_only,
            sources,
            pipe_instance.valves,
        )

        self.assertIn("keinen generierten Antworttext", final_answer)
        self.assertEqual(final_answer.count("## Nachweise"), 1)

    def test_pipe_source_inventory_question_avoids_duplicate_evidence(
        self,
    ) -> None:
        namespace = _pipe_namespace()
        pipe_instance = namespace["Pipe"]()
        pipe_instance.valves.SOURCE_MARKDOWN_MODE = "audit"
        pipe_instance.valves.APPEND_SOURCE_OVERVIEW = True
        sources = [
            {"name": "marker-a.md", "text": "Marker XYZ", "source_metadata": {"page": 1}},
            {"name": "marker-b.md", "text": "Marker XYZ", "source_metadata": {"page": 2}},
        ]

        self.assertTrue(
            namespace["_is_source_inventory_question"]("Welche Quellen enthalten den Marker XYZ?")
        )
        answer = namespace["_source_inventory_answer"](sources)
        final_answer = namespace["_compose_final_answer"](
            answer,
            sources,
            pipe_instance.valves,
        )

        self.assertIn("folgende Dokumente", final_answer)
        self.assertIn("marker-a.md", final_answer)
        self.assertEqual(final_answer.count("## Nachweise"), 1)

    def test_pipe_emits_citation_event_payload_for_audit_sources(self) -> None:
        namespace = _pipe_namespace()
        source = namespace["_normalize_sources"](
            [
                {
                    "name": "dienstleister.pdf",
                    "preview_url": "https://connector.example/api/openwebui/sources/preview?token=signed",
                    "text": "Prüfung vor Beauftragung erforderlich.",
                    "source_metadata": {
                        "page": 4,
                        "section": "Freigabeprozess",
                        "locator_quality": "page",
                    },
                }
            ],
            connector_base_url="http://connector:8080",
            allow_connector_source_links=False,
        )[0]

        event = namespace["_citation_event"](source)

        self.assertEqual(event["type"], "citation")
        self.assertEqual(event["data"]["document"], ["Prüfung vor Beauftragung erforderlich."])
        self.assertEqual(event["data"]["metadata"][0]["source_id"], "S1")
        self.assertEqual(event["data"]["metadata"][0]["page"], 4)
        self.assertEqual(event["data"]["metadata"][0]["section"], "Freigabeprozess")
        self.assertEqual(event["data"]["metadata"][0]["locator_quality"], "page")
        self.assertEqual(
            event["data"]["source"]["url"],
            "https://connector.example/api/openwebui/sources/preview?token=signed",
        )
        self.assertIn("Seite 4", event["data"]["source"]["name"])

    def test_pipe_audit_mode_keeps_connector_preview_but_filters_proxy_urls(self) -> None:
        namespace = _pipe_namespace()

        sources = namespace["_normalize_sources"](
            [
                {
                    "name": "preview.pdf",
                    "preview_url": "http://connector:8080/api/openwebui/sources/preview?token=signed",
                    "text": "Dieser Link ist eine geprüfte Connector-Preview.",
                },
                {
                    "name": "proxy.md",
                    "preview_url": "http://connector:8080/api/openwebui/proxy/chat",
                    "text": "Dieser Backend-Link darf nicht sichtbar werden.",
                },
            ],
            connector_base_url="http://connector:8080",
            allow_connector_source_links=False,
        )

        self.assertEqual(
            sources[0]["preview_url"],
            "http://connector:8080/api/openwebui/sources/preview?token=signed",
        )
        self.assertNotIn("preview_url", sources[1])

    def test_pipe_audit_mode_handles_conflicting_and_empty_sources(self) -> None:
        namespace = _pipe_namespace()
        pipe_instance = namespace["Pipe"]()
        pipe_instance.valves.SOURCE_MARKDOWN_MODE = "audit"
        pipe_instance.valves.APPEND_SOURCE_OVERVIEW = True

        conflicting = namespace["_source_markdown"](
            [
                {
                    "name": "alt.pdf",
                    "text": "Teamleitung genügt.",
                    "source_metadata": {"page": 3, "conflict": True},
                },
                {
                    "name": "neu.pdf",
                    "text": "Datenschutz und Fachbereich müssen freigeben.",
                    "source_metadata": {"page": 5},
                },
            ],
            mode="audit",
        )
        empty = namespace["_source_markdown"]([], mode="audit")

        self.assertIn("widersprüchlich", conflicting)
        self.assertIn("keine ausreichend belastbare Quelle", empty)

    def test_pipe_completion_status_counts_grouped_sources_and_hits(self) -> None:
        namespace = _pipe_namespace()
        sources = [
            {
                "name": "report.pdf",
                "text": "Erster Treffer im Report.",
                "score": 0.91,
                "source_metadata": {"path": "/report.pdf", "page": 1},
            },
            {
                "name": "report.pdf",
                "text": "Zweiter Treffer im selben Report.",
                "score": 0.86,
                "source_metadata": {"path": "/report.pdf", "page": 2},
            },
            {
                "name": "policy.pdf",
                "text": "Treffer in einem anderen Dokument.",
                "score": 0.78,
                "source_metadata": {"path": "/policy.pdf", "page": 1},
            },
        ]

        group_count = len(namespace["_group_sources"](sources))
        status = namespace["_completion_status"](
            group_count,
            1.2,
            generated=True,
            hit_count=len(sources),
        )

        self.assertIn("2 Quellen", status)
        self.assertIn("3 Treffer", status)

        single_status = namespace["_completion_status"](1, 0.4, generated=True, hit_count=4)
        self.assertIn("1 Quelle", single_status)
        self.assertIn("4 Treffer", single_status)

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
        self.assertNotIn("LANGUAGE", pipe.valves)

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
                self.assertNotIn("LANGUAGE", pipe.valves)
                self.assertEqual(tool.payload["meta"]["manifest"]["language"], language)
                self.assertIn(language, tool.content)


def _pipe_namespace() -> dict[str, object]:
    inputs = DatasetArtifactInputs(
        namespace="ragflow",
        repo_id="repo-1",
        dataset_id="dataset-1234567890",
        dataset_name="Demo Library",
        ragflow_chat_id="chat-1",
        proxy_base_url="http://connector:8080",
    )
    namespace: dict[str, object] = {}
    pipe = build_pipe_spec(inputs)
    exec(compile(pipe.content, "<openwebui-pipe>", "exec"), namespace)
    return namespace


if __name__ == "__main__":
    unittest.main()
