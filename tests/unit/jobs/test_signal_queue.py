from __future__ import annotations

import unittest
from unittest.mock import patch

from seafile_ragflow_connector.jobs.job_store import JobSignalQueue


class _FakeRedisClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class JobSignalQueueTests(unittest.TestCase):
    def test_close_closes_redis_client(self) -> None:
        client = _FakeRedisClient()

        with patch("redis.Redis.from_url", return_value=client):
            queue = JobSignalQueue("redis://127.0.0.1:6379/0")

        queue.close()

        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
