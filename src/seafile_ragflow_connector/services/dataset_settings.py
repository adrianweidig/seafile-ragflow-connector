from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.services.template_payload_builder import dataset_settings_fingerprint


@dataclass(frozen=True)
class DatasetSettingsSnapshotData:
    dataset_id: str
    settings_hash: str
    settings_payload: dict[str, Any]


class DatasetSettingsService:
    def __init__(self, ragflow_client: RAGFlowClient) -> None:
        self.ragflow_client = ragflow_client

    def refresh(self, dataset_id: str) -> DatasetSettingsSnapshotData:
        dataset = self.ragflow_client.get_dataset(dataset_id)
        return DatasetSettingsSnapshotData(
            dataset_id=dataset_id,
            settings_hash=dataset_settings_fingerprint(dataset),
            settings_payload=dataset,
        )

