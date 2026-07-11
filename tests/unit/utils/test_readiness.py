from __future__ import annotations

from seafile_ragflow_connector.utils.readiness import ReadinessCache


def test_readiness_cache_reuses_value_within_ttl() -> None:
    cache: ReadinessCache[dict[str, int]] = ReadinessCache(ttl_seconds=60)
    calls = 0

    def load() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"calls": calls}

    assert cache.get(load) == {"calls": 1}
    assert cache.get(load) == {"calls": 1}
    assert calls == 1
