from __future__ import annotations

import unittest

from seafile_ragflow_connector.jobs.types import JobType
from seafile_ragflow_connector.sync.delta_sync import map_commit_diff_to_jobs


class DeltaSyncTests(unittest.TestCase):
    def test_maps_modified_to_upload(self) -> None:
        jobs = map_commit_diff_to_jobs("repo", [{"op": "modified", "path": "/src/main.ada"}])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].job_type, JobType.UPLOAD_FILE)
        self.assertEqual(jobs[0].file_path, "/src/main.ada")

    def test_maps_removed_to_delete(self) -> None:
        jobs = map_commit_diff_to_jobs("repo", [{"op": "removed", "path": "/src/main.ada"}])
        self.assertEqual(jobs[0].job_type, JobType.DELETE_FILE)

    def test_maps_rename_to_delete_and_upload(self) -> None:
        jobs = map_commit_diff_to_jobs(
            "repo",
            [{"op": "renamed", "old_path": "/old.ada", "new_path": "/new.ada"}],
        )
        self.assertEqual([job.job_type for job in jobs], [JobType.DELETE_FILE, JobType.UPLOAD_FILE])
        self.assertEqual(jobs[0].file_path, "/old.ada")
        self.assertEqual(jobs[1].file_path, "/new.ada")


if __name__ == "__main__":
    unittest.main()
