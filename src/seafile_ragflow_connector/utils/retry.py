from __future__ import annotations

import random


def exponential_backoff_seconds(
    attempt: int,
    *,
    base_seconds: int = 30,
    max_seconds: int = 3600,
    jitter_ratio: float = 0.2,
) -> int:
    raw = min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))
    jitter = raw * jitter_ratio
    return int(max(1, raw + random.uniform(-jitter, jitter)))

