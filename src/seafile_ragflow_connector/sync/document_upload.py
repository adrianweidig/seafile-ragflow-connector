from __future__ import annotations

from dataclasses import dataclass

from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.clients.seafile_sync import SeafileSyncClient
from seafile_ragflow_connector.domain.file_classification import FilePolicy, classify_file
from seafile_ragflow_connector.domain.ingestion_artifacts import (
    IngestionArtifact,
    build_ragflow_document_metadata,
    prepare_ingestion_artifact,
)
from seafile_ragflow_connector.sync.dataset_settings import DatasetSettingsService


@dataclass(frozen=True)
class UploadResult:
    document_id: str
    artifact: IngestionArtifact
    dataset_settings_hash: str | None


class DocumentUploadService:
    def __init__(
        self,
        seafile_client: SeafileSyncClient,
        ragflow_client: RAGFlowClient,
        *,
        file_policy: FilePolicy | None = None,
        dataset_settings_service: DatasetSettingsService | None = None,
        refresh_dataset_settings: bool = True,
    ) -> None:
        self.seafile_client = seafile_client
        self.ragflow_client = ragflow_client
        self.file_policy = file_policy or FilePolicy()
        self.dataset_settings_service = dataset_settings_service
        self.refresh_dataset_settings = refresh_dataset_settings

    def upload_file(self, repo_id: str, dataset_id: str, path: str) -> UploadResult | None:
        data = self.seafile_client.download_file(repo_id, path)
        classification = classify_file(path, data, self.file_policy)
        if not classification.should_ingest:
            return None

        settings_hash = None
        if self.refresh_dataset_settings and self.dataset_settings_service:
            settings_hash = self.dataset_settings_service.refresh(dataset_id).settings_hash

        artifact = prepare_ingestion_artifact(classification, data)
        document = self.ragflow_client.upload_document(
            dataset_id,
            document_name=artifact.document_name,
            content=artifact.content,
            mime_type=artifact.mime_type,
        )
        document_id = str(document.get("id") or document.get("document_id"))
        metadata = build_ragflow_document_metadata(artifact, repo_id=repo_id, path=path)
        self.ragflow_client.update_document_metadata(dataset_id, document_id, metadata)
        return UploadResult(
            document_id=document_id,
            artifact=artifact,
            dataset_settings_hash=settings_hash,
        )
