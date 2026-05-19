from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.services.template_payload_builder import (
    TemplateError,
    build_dataset_create_payload,
    dataset_settings_fingerprint,
)
from seafile_ragflow_connector.utils.naming import build_dataset_name, slugify


class DatasetProvisioningError(RuntimeError):
    pass


@dataclass(frozen=True)
class LibrarySource:
    repo_id: str
    name: str
    owner_email: str | None = None


@dataclass(frozen=True)
class DatasetProvisioningResult:
    repo_id: str
    dataset_id: str
    dataset_name: str
    created: bool
    template_hash: str | None
    settings_hash: str
    settings_payload: dict[str, Any]


def select_template_dataset(datasets: list[dict[str, Any]], template_name: str) -> dict[str, Any]:
    matches = [dataset for dataset in datasets if dataset.get("name") == template_name]
    if not matches:
        msg = f"RAGFlow template dataset not found: {template_name}"
        raise DatasetProvisioningError(msg)
    if len(matches) > 1:
        msg = f"RAGFlow template dataset is not unique: {template_name}"
        raise DatasetProvisioningError(msg)
    return matches[0]


def build_seafile_description(library: LibrarySource) -> str:
    lines = [
        "Source: Seafile",
        f"Library: {library.name}",
        f"Repo ID: {library.repo_id}",
    ]
    if library.owner_email:
        lines.append(f"Owner: {library.owner_email}")
    return "\n".join(lines)


class DatasetProvisioner:
    def __init__(
        self,
        ragflow_client: RAGFlowClient,
        *,
        template_dataset_name: str = "connector_template",
        dataset_prefix: str = "seafile__",
        dataset_name_max_length: int = 128,
    ) -> None:
        self.ragflow_client = ragflow_client
        self.template_dataset_name = template_dataset_name
        self.dataset_prefix = dataset_prefix
        self.dataset_name_max_length = dataset_name_max_length

    def ensure_dataset(self, library: LibrarySource) -> DatasetProvisioningResult:
        dataset_name = build_dataset_name(
            library.name,
            library.repo_id,
            prefix=self.dataset_prefix,
            max_length=self.dataset_name_max_length,
        )
        existing = self.ragflow_client.list_datasets(name=dataset_name)
        if existing:
            dataset = existing[0]
            settings_hash = dataset_settings_fingerprint(dataset)
            return DatasetProvisioningResult(
                repo_id=library.repo_id,
                dataset_id=str(dataset["id"]),
                dataset_name=str(dataset["name"]),
                created=False,
                template_hash=None,
                settings_hash=settings_hash,
                settings_payload=dataset,
            )

        template = select_template_dataset(
            self.ragflow_client.list_datasets(name=self.template_dataset_name),
            self.template_dataset_name,
        )
        try:
            payload = build_dataset_create_payload(
                template,
                dataset_name,
                append_description=build_seafile_description(library),
            )
        except TemplateError as exc:
            raise DatasetProvisioningError(str(exc)) from exc

        created = self.ragflow_client.create_dataset(payload)
        settings_hash = dataset_settings_fingerprint(created)
        return DatasetProvisioningResult(
            repo_id=library.repo_id,
            dataset_id=str(created["id"]),
            dataset_name=str(created.get("name", dataset_name)),
            created=True,
            template_hash=dataset_settings_fingerprint(template),
            settings_hash=settings_hash,
            settings_payload=created,
        )

    @staticmethod
    def library_slug(library_name: str) -> str:
        return slugify(library_name)

