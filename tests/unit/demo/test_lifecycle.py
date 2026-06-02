from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from seafile_ragflow_connector.demo.lifecycle import (
    CANONICAL_DEMO_LIBRARIES,
    _rewrite_seafile_service_url,
    is_safe_demo_dataset_name,
    is_safe_demo_library_name,
    is_safe_demo_openwebui_artifact,
    write_demo_testset,
)


class DemoLifecycleTests(unittest.TestCase):
    def test_safe_cleanup_matchers_only_accept_demo_names(self) -> None:
        self.assertTrue(is_safe_demo_library_name("Connector Demo Wissen"))
        self.assertTrue(is_safe_demo_library_name("Demo RAGFlow OpenWebUI Bibliothek 20260602"))
        self.assertTrue(is_safe_demo_library_name("RAG Demo Bibliothek 20260522_110601"))
        self.assertTrue(is_safe_demo_dataset_name("seafile__connector-demo-wissen__repo"))
        self.assertTrue(
            is_safe_demo_dataset_name("seafile__demo-ragflow-openwebui-bibliothek-20260602__repo")
        )
        self.assertTrue(
            is_safe_demo_openwebui_artifact(
                "ragflow_pipe_seafile_demo_ragflow_openwebui_bibliothek_20260602"
            )
        )
        self.assertTrue(is_safe_demo_openwebui_artifact("ragflow_tool_seafile_rag_demo_bibliothek_x"))

        self.assertFalse(is_safe_demo_library_name("Meine Bibliothek"))
        self.assertFalse(is_safe_demo_library_name("testbibliothek"))
        self.assertFalse(is_safe_demo_dataset_name("connector_template"))
        self.assertFalse(is_safe_demo_dataset_name("seafile__meine-bibliothek__repo"))
        self.assertFalse(is_safe_demo_openwebui_artifact("ragflow_tool_seafile_meine_bibliothek"))

    def test_write_demo_testset_creates_expected_file_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixtures = write_demo_testset(Path(temp_dir))

            self.assertEqual(set(fixtures), set(CANONICAL_DEMO_LIBRARIES))
            all_files = [Path(path) for paths in fixtures.values() for path in paths]
            suffixes = {path.suffix for path in all_files}
            self.assertIn(".pdf", suffixes)
            self.assertIn(".docx", suffixes)
            self.assertIn(".pptx", suffixes)
            self.assertIn(".xlsx", suffixes)
            self.assertIn(".csv", suffixes)
            self.assertIn(".md", suffixes)
            self.assertIn(".txt", suffixes)

            docx = next(path for path in all_files if path.suffix == ".docx")
            xlsx = next(path for path in all_files if path.suffix == ".xlsx")
            pptx = next(path for path in all_files if path.suffix == ".pptx")
            for office_file in (docx, xlsx, pptx):
                with zipfile.ZipFile(office_file) as archive:
                    self.assertIn("[Content_Types].xml", archive.namelist())
                    if office_file.suffix == ".pptx":
                        slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")
                        self.assertIn("<p:spPr>", slide_xml)
                        self.assertIn("<a:xfrm>", slide_xml)

    def test_rewrites_localhost_seafile_upload_links_to_service_base_url(self) -> None:
        settings = _Settings()

        rewritten = _rewrite_seafile_service_url(
            "http://127.0.0.1/seafhttp/upload-api/token",
            settings,  # type: ignore[arg-type]
        )

        self.assertEqual(rewritten, "http://seafile/seafhttp/upload-api/token")


class _Settings:
    seafile_base_url = "http://seafile"


if __name__ == "__main__":
    unittest.main()
