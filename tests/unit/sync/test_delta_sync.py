from __future__ import annotations

import unittest

from seafile_ragflow_connector.jobs.types import JobType
from seafile_ragflow_connector.sync.delta_sync import (
    SnapshotEntry,
    capture_commit_snapshot,
    diff_snapshots,
    map_commit_diff_to_jobs,
)


class _SnapshotClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def list_dir_at_commit(self, repo_id: str, commit_id: str, path: str = "/"):
        self.calls.append((repo_id, commit_id, path))
        if path == "/":
            return [
                {"name": "docs", "type": "dir", "id": "dir-1"},
                {"name": "root.txt", "type": "file", "id": "obj-root", "size": 4},
            ]
        if path == "/docs":
            return [{"name": "a.txt", "type": "file", "id": "obj-a", "size": 1}]
        return []


def _entry(path: str, object_id: str) -> SnapshotEntry:
    return SnapshotEntry(
        path=path,
        normalized_path=path,
        object_id=object_id,
        size=1,
        mtime=1,
        is_directory=False,
        raw={},
    )


class DeltaSyncTests(unittest.TestCase):
    def test_captures_recursive_tree_at_one_immutable_commit(self) -> None:
        client = _SnapshotClient()

        entries = capture_commit_snapshot(client, "repo", "commit-1")

        self.assertEqual(
            [entry.normalized_path for entry in entries],
            ["/docs", "/docs/a.txt", "/root.txt"],
        )
        self.assertEqual(
            client.calls,
            [("repo", "commit-1", "/"), ("repo", "commit-1", "/docs")],
        )

    def test_snapshot_diff_uses_object_ids_for_rename_modify_add_and_remove(self) -> None:
        baseline = [
            _entry("/old.txt", "same"),
            _entry("/modified.txt", "old"),
            _entry("/removed.txt", "removed"),
        ]
        target = [
            _entry("/new.txt", "same"),
            _entry("/modified.txt", "new"),
            _entry("/added.txt", "added"),
        ]

        changes = diff_snapshots(baseline, target)

        self.assertEqual(
            [(change.operation, change.old_path, change.path) for change in changes],
            [
                ("renamed", "/old.txt", "/new.txt"),
                ("removed", None, "/removed.txt"),
                ("new", None, "/added.txt"),
                ("modified", None, "/modified.txt"),
            ],
        )

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
