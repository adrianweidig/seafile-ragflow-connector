from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    checks: dict[str, bool]


def combine_health(checks: dict[str, bool]) -> HealthStatus:
    return HealthStatus(ok=all(checks.values()), checks=checks)

