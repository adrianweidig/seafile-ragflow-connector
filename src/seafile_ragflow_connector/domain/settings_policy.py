from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetSettingsDecision:
    changed: bool
    enqueue_reparse: bool
    reason: str


def evaluate_dataset_settings_change(
    previous_hash: str | None,
    current_hash: str,
    *,
    reparse_on_change: bool,
) -> DatasetSettingsDecision:
    if previous_hash is None:
        return DatasetSettingsDecision(changed=False, enqueue_reparse=False, reason="first_observation")
    if previous_hash == current_hash:
        return DatasetSettingsDecision(changed=False, enqueue_reparse=False, reason="unchanged")
    return DatasetSettingsDecision(
        changed=True,
        enqueue_reparse=reparse_on_change,
        reason="changed_reparse_enabled" if reparse_on_change else "changed_reparse_disabled",
    )

