from __future__ import annotations

import unittest

from seafile_ragflow_connector.jobs.types import JobPriority, JobSpec, JobType


class JobPriorityTests(unittest.TestCase):
    def test_delete_and_dataset_provisioning_are_high_priority(self) -> None:
        self.assertEqual(JobSpec(JobType.DELETE_FILE).resolved_priority(), JobPriority.HIGH)
        self.assertEqual(
            JobSpec(JobType.ENSURE_RAGFLOW_DATASET).resolved_priority(),
            JobPriority.HIGH,
        )

    def test_reconcile_and_reparse_are_low_priority(self) -> None:
        self.assertEqual(JobSpec(JobType.RECONCILE_LIBRARY).resolved_priority(), JobPriority.LOW)
        self.assertEqual(JobSpec(JobType.REPARSE_DOCUMENTS).resolved_priority(), JobPriority.LOW)

    def test_default_priority_is_normal(self) -> None:
        self.assertEqual(JobSpec(JobType.UPLOAD_FILE).resolved_priority(), JobPriority.NORMAL)


if __name__ == "__main__":
    unittest.main()
