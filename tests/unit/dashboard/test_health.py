from __future__ import annotations

import unittest

from seafile_ragflow_connector.dashboard.health import _check_sync_jobs


class DashboardHealthTests(unittest.TestCase):
    def test_sync_jobs_health_exposes_counts_for_localized_ui(self) -> None:
        result = _check_sync_jobs(
            {
                "running_jobs": 2,
                "queued_or_retrying_jobs": 0,
                "failed_jobs": 0,
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["running_jobs"], 2)
        self.assertEqual(result["queued_or_retrying_jobs"], 0)
        self.assertEqual(result["failed_jobs"], 0)


if __name__ == "__main__":
    unittest.main()
