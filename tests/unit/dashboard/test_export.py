from __future__ import annotations

import unittest
from io import BytesIO
from zipfile import ZipFile

from seafile_ragflow_connector.dashboard.export import build_audit_workbook


class DashboardAuditExportTests(unittest.TestCase):
    def test_build_audit_workbook_creates_multisheet_xlsx(self) -> None:
        workbook = build_audit_workbook(
            {
                "generated_at": "2026-05-20T10:00:00Z",
                "status": {"state": "wartend", "errors_count": 0},
                "metrics": {"libraries": 1, "files": 2, "sync_runs": 1, "changes": 1, "logs": 1},
                "systems": {
                    "source": {
                        "libraries": [
                            {
                                "repo_id": "repo-1",
                                "name": "Lib",
                                "status": "active",
                                "head_commit_id": "head",
                                "last_synced_commit_id": "synced",
                                "last_error": None,
                            }
                        ]
                    },
                    "target": {
                        "datasets": [
                            {
                                "repo_id": "repo-1",
                                "dataset_id": "dataset-1",
                                "dataset_name": "Lib",
                                "template_hash": "hash",
                            }
                        ]
                    },
                },
                "diagnostics": {"configuration": {"ragflow_api_key": "***"}},
                "sync_runs": [{"sync_id": "sync-1", "status": "succeeded"}],
                "changes": [{"sync_id": "sync-1", "object_name": "a.txt", "status": "synced"}],
                "logs": [{"level": "info", "message": "done"}],
                "openwebui": {"status": {"status": "disabled"}, "mappings": []},
                "export_limits": {"max_log_entries": 5000},
            }
        )

        self.assertTrue(workbook.startswith(b"PK"))
        with ZipFile(BytesIO(workbook)) as archive:
            names = set(archive.namelist())
            self.assertIn("xl/workbook.xml", names)
            self.assertIn("xl/styles.xml", names)
            self.assertIn("xl/worksheets/sheet1.xml", names)
            workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
            first_sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")

        self.assertIn('name="Overview"', workbook_xml)
        self.assertIn('name="Sync Runs"', workbook_xml)
        self.assertIn('name="Changes"', workbook_xml)
        self.assertIn('name="OpenWebUI"', workbook_xml)
        self.assertIn("Connector-Zustand", first_sheet)


if __name__ == "__main__":
    unittest.main()
