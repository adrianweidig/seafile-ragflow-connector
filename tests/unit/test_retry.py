from __future__ import annotations

import unittest

from seafile_ragflow_connector.utils.retry import exponential_backoff_seconds


class RetryTests(unittest.TestCase):
    def test_backoff_is_capped(self) -> None:
        value = exponential_backoff_seconds(20, base_seconds=30, max_seconds=60, jitter_ratio=0)
        self.assertEqual(value, 60)

    def test_backoff_has_minimum(self) -> None:
        value = exponential_backoff_seconds(0, base_seconds=1, max_seconds=60, jitter_ratio=0)
        self.assertEqual(value, 1)


if __name__ == "__main__":
    unittest.main()

