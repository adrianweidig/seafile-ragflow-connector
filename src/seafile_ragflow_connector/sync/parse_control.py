from __future__ import annotations

from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.sync.dataset_settings import DatasetSettingsService


class ParseControlService:
    def __init__(
        self,
        ragflow_client: RAGFlowClient,
        *,
        dataset_settings_service: DatasetSettingsService | None = None,
        refresh_dataset_settings: bool = True,
    ) -> None:
        self.ragflow_client = ragflow_client
        self.dataset_settings_service = dataset_settings_service
        self.refresh_dataset_settings = refresh_dataset_settings

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> str | None:
        settings_hash = None
        if self.refresh_dataset_settings and self.dataset_settings_service:
            settings_hash = self.dataset_settings_service.refresh(dataset_id).settings_hash
        self.ragflow_client.parse_documents(dataset_id, document_ids)
        return settings_hash
