from __future__ import annotations

from dataclasses import dataclass, field

from seafile_ragflow_connector.jobs.types import JobSpec


@dataclass(frozen=True)
class ReconcilePlan:
    jobs: list[JobSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Reconciler:
    def plan_library_reconcile(self) -> ReconcilePlan:
        return ReconcilePlan(
            warnings=["library reconcile planning requires live Seafile and DB state"]
        )
