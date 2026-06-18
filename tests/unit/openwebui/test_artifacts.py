from __future__ import annotations

import asyncio
import json
import unittest
from importlib import resources

import httpx

import seafile_ragflow_connector.openwebui.templates.pipe as pipe_templates
from seafile_ragflow_connector.openwebui.artifacts import (
    _PIPE_TEMPLATE_FRAGMENTS,
    DatasetArtifactInputs,
    _pipe_content,
    build_pipe_spec,
    build_tool_spec,
)


class OpenWebUIArtifactTests(unittest.TestCase):
    def test_pipe_template_is_composed_from_packaged_fragments(self) -> None:
        template_root = resources.files(pipe_templates)
        parts = [
            template_root.joinpath(fragment).read_text(encoding="utf-8")
            for fragment in _PIPE_TEMPLATE_FRAGMENTS
        ]

        self.assertGreater(len(parts), 3)
        self.assertTrue(all(part.strip() for part in parts))
        self.assertIn("class Pipe:", parts[0])
        self.assertIn("KONFIGURATIONSPRÜFUNG", parts[1])
        self.assertIn("OPTIONALER ANTWORT-SYNTHESE-FALLBACK", parts[2])
        self.assertIn("OPENWEBUI-EVENTS", parts[3])
        self.assertIn("FINALE CHAT-AUSGABE", parts[4])
        self.assertIn("TEXTBEREINIGUNG", parts[5])
        self.assertEqual("".join(parts), _pipe_content())
        self.assertFalse(
            resources.files("seafile_ragflow_connector.openwebui.templates")
            .joinpath("ragflow_dataset_pipe_chat_rag_polished.py.txt")
            .is_file()
        )

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
        self.assertIn("artifact_version: 27", tool.content)
        self.assertIn("artifact_version: 27", pipe.content)
        self.assertFalse(tool.valves["TLS_DEBUG"])
        self.assertEqual(tool.valves["SHOW_SOURCE_SCORES"], True)
        self.assertEqual(tool.valves["LANGUAGE"], "de")
        self.assertEqual(pipe.name, "Seafile · Demo Library")
        self.assertEqual(pipe.valves["MODEL_NAME"], "Seafile · Demo Library")
        self.assertEqual(pipe.valves["RAGFLOW_MODEL_ID"], "model")
        self.assertEqual(pipe.valves["SOURCE_DISPLAY_MODE"], "compact")
        self.assertEqual(pipe.valves["SOURCE_MARKDOWN_MODE"], "compact")
        self.assertEqual(pipe.valves["RETRIEVAL_ONLY_FALLBACK"], "brief")
        self.assertEqual(pipe.valves["EMIT_CITATION_EVENTS"], False)
        self.assertEqual(pipe.valves["APPEND_SOURCE_OVERVIEW"], True)
        self.assertEqual(pipe.valves["SHOW_SOURCE_SCORES"], True)
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
        self.assertIn("version: 3.10.0", pipe.content)
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
        self.assertIn('_clean(valves.RAGFLOW_MODEL_ID) or "model"', pipe.content)
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
        pipe_instance.valves.RAGFLOW_MODEL_ID = "ragflow-chat-model"
        pipe_instance.valves.SOURCE_DISPLAY_MODE = str(pipe.valves["SOURCE_DISPLAY_MODE"])
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
        self.assertEqual(payload["model"], "ragflow-chat-model")
        self.assertEqual(payload["ragflow"]["mode"], "chat")
        self.assertTrue(payload["openwebui"]["expects_generated_answer"])
        self.assertEqual(payload["openwebui"]["source_markdown_mode"], "compact")
        self.assertEqual(payload["openwebui"]["source_display_mode"], "markdown_audit")
        self.assertFalse(payload["openwebui"]["audit_evidence"])
        self.assertEqual(
            payload["extra_body"]["reference_metadata"]["fields"][:3],
            ["document_id", "document_name", "positions"],
        )
        self.assertTrue(payload["extra_body"]["reference_metadata"]["include"])
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

    def test_pipe_treats_file_content_questions_as_content_intent(self) -> None:
        namespace = _pipe_namespace()

        self.assertTrue(
            namespace["_is_content_question"]("Was sind die Inhalte der verschiedenen Dateien?")
        )
        self.assertTrue(namespace["_is_content_question"]("Du sollst mir die Inhalte geben."))
        self.assertFalse(
            namespace["_is_source_inventory_question"](
                "Was sind die Inhalte der verschiedenen Dateien?"
            )
        )
        self.assertFalse(
            namespace["_is_source_inventory_question"]("Du sollst mir die Inhalte geben.")
        )
        self.assertTrue(
            namespace["_is_source_inventory_question"]("Welche Quellen wurden gefunden?")
        )

    def test_pipe_final_answer_uses_compact_sources_by_default(self) -> None:
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
        self.assertNotIn("[S1]", final_answer)
        self.assertIn("## Quellen", final_answer)
        self.assertIn("### S1", final_answer)
        self.assertIn("report.pdf", final_answer)
        self.assertIn("Seite 2", final_answer)
        self.assertNotIn("chunk_id", final_answer)
        self.assertNotIn("document_id", final_answer)

    def test_pipe_curates_uncited_documents_for_normal_answers(self) -> None:
        namespace = _pipe_namespace()
        sources = [
            {
                "source_id": "S1",
                "name": "mobiles-arbeiten.pdf",
                "text": "Samstags sind maximal sechs Stunden mobiles Arbeiten möglich.",
                "source_metadata": {"document_id": "doc-mobile", "citation_id": 0},
            },
            {
                "source_id": "S2",
                "name": "mobiles-arbeiten.pdf",
                "text": "Mobile Arbeit am Samstag muss zwischen 06:00 und 19:00 Uhr liegen.",
                "source_metadata": {"document_id": "doc-mobile", "citation_id": 1},
            },
            {
                "source_id": "S3",
                "name": "codex-audit-e2e.md",
                "text": "Interner Audit-Marker ohne Bezug zu mobilem Arbeiten.",
                "source_metadata": {"document_id": "doc-audit", "citation_id": 2},
            },
        ]

        curated = namespace["_curate_sources_for_answer"](
            sources,
            "Samstags gilt eine Sechs-Stunden-Grenze. [S1]",
        )

        self.assertEqual(
            [source["name"] for source in curated],
            ["mobiles-arbeiten.pdf", "mobiles-arbeiten.pdf"],
        )

    def test_pipe_compact_mode_keeps_answer_without_markdown_block(self) -> None:
        namespace = _pipe_namespace()
        pipe_instance = namespace["Pipe"]()
        pipe_instance.valves.SOURCE_DISPLAY_MODE = "compact"
        pipe_instance.valves.SOURCE_MARKDOWN_MODE = "none"
        pipe_instance.valves.APPEND_SOURCE_OVERVIEW = False
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
        self.assertNotIn("## Nachweise", final_answer)

    def test_pipe_strips_legacy_appended_source_block_before_rendering_once(self) -> None:
        namespace = _pipe_namespace()
        pipe_instance = namespace["Pipe"]()
        pipe_instance.valves.SOURCE_DISPLAY_MODE = "markdown_audit"
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
        pipe_instance.valves.SOURCE_DISPLAY_MODE = "markdown_audit"
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
        pipe_instance.valves.SOURCE_DISPLAY_MODE = "markdown_audit"
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
            answer_origin="source_inventory",
        )

        self.assertIn("folgende Dokumente", final_answer)
        self.assertIn("marker-a.md", final_answer)
        self.assertIn("Quellen gefunden, aber keine generierte Antwort", final_answer)
        self.assertEqual(final_answer.count("## Nachweise"), 1)

    def test_pipe_source_inventory_origin_is_not_generated(self) -> None:
        namespace = _pipe_namespace()

        self.assertNotIn("source_inventory", namespace["ANSWER_GENERATED_ORIGINS"])
        self.assertIn("source_inventory", namespace["NON_GENERATED_ORIGINS"])
        self.assertIn(
            "Quellen gefunden, aber keine Antwort generiert",
            namespace["_completion_status"](
                2,
                0.1,
                answer_origin="source_inventory",
                hit_count=2,
            ),
        )

    def test_pipe_extract_answer_result_uses_only_canonical_paths(self) -> None:
        namespace = _pipe_namespace()

        openai_result = namespace["extract_answer_result"](
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Das Dokument regelt mobiles Arbeiten verbindlich. [S1]",
                        }
                    }
                ]
            }
        )
        self.assertEqual(
            openai_result.answer,
            "Das Dokument regelt mobiles Arbeiten verbindlich. [S1]",
        )
        self.assertEqual(openai_result.origin, "openai_message")
        self.assertEqual(openai_result.path, "choices[0].message.content")

        canonical_result = namespace["extract_answer_result"](
            {"data": {"answer": "RAGFlow liefert eine echte Antwort mit Satzstruktur."}}
        )
        self.assertEqual(canonical_result.origin, "canonical_answer")
        self.assertEqual(canonical_result.path, "data.answer")

        provider_marker_result = namespace["extract_answer_result"](
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Der Marker steht in der Testdatei [ID:3]. "
                                "{{source:1}} ##2$$"
                            ),
                        }
                    }
                ]
            }
        )
        self.assertIn("[ID:3]", provider_marker_result.answer)
        self.assertIn("{{source:1}}", provider_marker_result.answer)
        self.assertIn("##2$$", provider_marker_result.answer)

        for payload in (
            {"message": "dateiname.md", "sources": [{"content": "Ein Quellenchunk."}]},
            {"data": {"content": "dateiname.md"}, "sources": [{"content": "Ein Quellenchunk."}]},
        ):
            with self.subTest(payload=payload):
                result = namespace["extract_answer_result"](payload)
                self.assertEqual(result.answer, "")
                self.assertEqual(result.origin, "retrieval_only")

        for answer in (
            "ERROR: Model(@None) not authorized",
            "**ERROR**: Model(@None) not authorized",
        ):
            with self.subTest(answer=answer):
                backend_error_result = namespace["extract_answer_result"](
                    {
                        "data": {"answer": answer},
                        "reference": {
                            "chunks": [
                                {
                                    "document_name": "quelle.md",
                                    "content": "Ein verwertbarer Quellenchunk.",
                                }
                            ]
                        },
                    }
                )
                self.assertEqual(backend_error_result.answer, "")
                self.assertEqual(backend_error_result.origin, "retrieval_only")
                self.assertTrue(
                    any("backend error" in warning for warning in backend_error_result.warnings)
                )

    def test_pipe_extract_answer_result_rejects_source_markdown_only(self) -> None:
        namespace = _pipe_namespace()
        result = namespace["extract_answer_result"](
            {
                "answer": (
                    "## Nachweise\n\n"
                    "| ID | Gestützte Aussage | Dokument | Fundstelle | Relevanz | Öffnen |\n"
                    "|---|---|---|---|---|---|\n"
                    "| S1 | Treffer | quelle.md | Seite 1 | hoch | Preview öffnen |"
                ),
                "sources": [{"name": "quelle.md", "text": "Ein echter Quellenchunk."}],
            }
        )

        self.assertEqual(result.answer, "")
        self.assertEqual(result.origin, "retrieval_only")
        self.assertTrue(any("source markdown" in warning for warning in result.warnings))

    def test_pipe_http_status_uses_safe_connector_denial_message(self) -> None:
        namespace = _pipe_namespace()
        response = httpx.Response(
            403,
            json={"error": "forbidden", "message": "Kein Zugriff auf diese Bibliothek."},
        )

        message = namespace["_http_status_user_message"](403, response, "safe")

        self.assertEqual(message, "Kein Zugriff auf diese Bibliothek.")

    def test_pipe_returns_plain_connector_denial_without_error_card(self) -> None:
        namespace = _pipe_namespace()
        pipe = namespace["Pipe"]()
        pipe.valves.CONNECTOR_PROXY_BASE_URL = "http://connector:8080"
        pipe.valves.CONNECTOR_PROXY_SHARED_SECRET = "test-secret"
        pipe.valves.DATASET_ID = "dataset-123"

        async def fake_post_json(*_args: object, **_kwargs: object) -> dict[str, object]:
            raise namespace["PipeError"](
                "Kein Zugriff auf diese Bibliothek.",
                status="Kein Zugriff auf diese Bibliothek.",
            )

        namespace["_post_json"] = fake_post_json

        result = asyncio.run(
            pipe.pipe(
                {"messages": [{"role": "user", "content": "Admin-Dokument"}]},
                __event_emitter__=None,
                __user__={"username": "julien", "email": "julien@top.secret"},
            )
        )

        self.assertEqual(result, "Kein Zugriff auf diese Bibliothek.")
        self.assertNotIn("RAGFlow-Anfrage fehlgeschlagen", result)

    def test_pipe_http_status_keeps_untrusted_forbidden_messages_generic(self) -> None:
        namespace = _pipe_namespace()
        response = httpx.Response(
            403,
            json={"error": "forbidden", "message": "user_not_in_library_acl"},
        )

        message = namespace["_http_status_user_message"](403, response, "safe")

        self.assertIn("RAGFlow-Proxy hat die Anfrage abgelehnt", message)

    def test_pipe_extract_sources_uses_prioritized_references_once(self) -> None:
        namespace = _pipe_namespace()
        reference = {
            "chunks": {
                "1": {
                    "id": "chunk-1",
                    "document_id": "doc-1",
                    "document_name": "quelle.md",
                    "content": "Der relevante Satz steht hier.",
                    "score": 0.91,
                }
            }
        }

        extracted = namespace["_extract_sources"](
            {
                "choices": [{"message": {"content": "Antwort.", "reference": reference}}],
                "data": {"references": reference},
                "references": reference,
            }
        )
        normalized = namespace["_normalize_sources"](extracted, limit=20, show_debug=True)

        self.assertEqual(len(extracted), 1)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["source_metadata"]["document_id"], "doc-1")

    def test_pipe_normalize_sources_sorts_unknown_scores_after_scored_sources(self) -> None:
        namespace = _pipe_namespace()
        normalized = namespace["_normalize_sources"](
            [
                {"name": "unknown.md", "text": "Quelle ohne Score."},
                {"name": "high.md", "text": "Quelle mit Score.", "score": 0.9},
            ],
            limit=20,
        )

        self.assertEqual([item["name"] for item in normalized], ["high.md", "unknown.md"])

    def test_pipe_audit_mode_warns_without_adding_fake_source_marker(self) -> None:
        namespace = _pipe_namespace()
        pipe_instance = namespace["Pipe"]()
        pipe_instance.valves.SOURCE_DISPLAY_MODE = "markdown_audit"
        pipe_instance.valves.SOURCE_MARKDOWN_MODE = "audit"
        pipe_instance.valves.APPEND_SOURCE_OVERVIEW = True
        sources = [
            {
                "name": "audit.md",
                "text": "Der Auszug belegt die Antwort.",
                "source_metadata": {"page": 2},
            }
        ]

        final_answer = namespace["_compose_final_answer"](
            "Dies ist eine inhaltliche Antwort ohne explizite Quellenmarke.",
            sources,
            pipe_instance.valves,
        )

        self.assertNotIn("_ensure_audit_marker", namespace)
        self.assertNotRegex(final_answer.split("\n\n", 1)[0], r"\[S1\]$")
        self.assertIn("keine expliziten Quellenmarken", final_answer)

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
        pipe_instance.valves.SOURCE_DISPLAY_MODE = "markdown_audit"
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
            answer_origin="canonical_answer",
            hit_count=len(sources),
        )

        self.assertIn("2 Quellen", status)
        self.assertIn("3 Treffer", status)

        single_status = namespace["_completion_status"](
            1,
            0.4,
            answer_origin="canonical_answer",
            hit_count=4,
        )
        self.assertIn("1 Quelle", single_status)
        self.assertIn("4 Treffer", single_status)

        retrieval_status = namespace["_completion_status"](
            1,
            0.4,
            answer_origin="retrieval_only",
            hit_count=1,
        )
        self.assertIn("keine Antwort generiert", retrieval_status)

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
