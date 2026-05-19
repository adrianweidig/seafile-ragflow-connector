from __future__ import annotations

from seafile_ragflow_connector.clients.ragflow import RAGFlowClient


class SafeDeleteError(RuntimeError):
    pass


class DocumentDeleteService:
    def __init__(self, ragflow_client: RAGFlowClient, *, enabled: bool = True) -> None:
        self.ragflow_client = ragflow_client
        self.enabled = enabled

    def delete_document(self, dataset_id: str, document_id: str | None) -> bool:
        if not self.enabled:
            return False
        if not document_id:
            msg = "refusing to delete without a known RAGFlow document id"
            raise SafeDeleteError(msg)
        self.ragflow_client.delete_documents(dataset_id, [document_id])
        return True

