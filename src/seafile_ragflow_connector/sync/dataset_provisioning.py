from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.domain.naming import build_dataset_name, slugify
from seafile_ragflow_connector.domain.ragflow_defaults import build_template_dataset_payload
from seafile_ragflow_connector.domain.template_payload_builder import (
    TemplateError,
    build_dataset_create_payload,
    dataset_settings_fingerprint,
)


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
        template_auto_create: bool = True,
        template_required: bool = True,
        dataset_prefix: str = "RAG_",
        dataset_name_max_length: int = 128,
    ) -> None:
        self.ragflow_client = ragflow_client
        self.template_dataset_name = template_dataset_name
        self.template_auto_create = template_auto_create
        self.template_required = template_required
        self.dataset_prefix = dataset_prefix
        self.dataset_name_max_length = dataset_name_max_length
        self.log = structlog.get_logger(__name__)

    def ensure_dataset(self, library: LibrarySource) -> DatasetProvisioningResult:
        dataset_name = build_dataset_name(
            library.name,
            library.repo_id,
            prefix=self.dataset_prefix,
            max_length=self.dataset_name_max_length,
        )
        existing = self.ragflow_client.list_datasets(name=dataset_name)
        if existing:
            if self.template_auto_create or self.template_required:
                self.ensure_template_dataset()
            dataset = existing[0]
            return self.result_from_existing_dataset(library, dataset)

        template = self.ensure_template_dataset()
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

    def result_from_existing_dataset(
        self,
        library: LibrarySource,
        dataset: dict[str, Any],
    ) -> DatasetProvisioningResult:
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

    def ensure_template_dataset(self) -> dict[str, Any]:
        datasets = self.ragflow_client.list_datasets(name=self.template_dataset_name)
        matches = [
            dataset for dataset in datasets if dataset.get("name") == self.template_dataset_name
        ]
        if len(matches) > 1:
            msg = f"RAGFlow template dataset is not unique: {self.template_dataset_name}"
            raise DatasetProvisioningError(msg)
        if matches:
            desired = build_template_dataset_payload(self.template_dataset_name)
            return self._repair_template_dataset(matches[0], desired)
        if not self.template_auto_create:
            required = "required " if self.template_required else ""
            msg = (
                f"RAGFlow {required}template dataset not found and auto-create is disabled: "
                f"{self.template_dataset_name}"
            )
            raise DatasetProvisioningError(msg)
        payload = build_template_dataset_payload(self.template_dataset_name)
        created = self.ragflow_client.create_dataset(payload)
        self.log.info(
            "ragflow.template_dataset.created",
            template_dataset_name=self.template_dataset_name,
            dataset_id=created.get("id"),
        )
        return created

    def _repair_template_dataset(
        self,
        template: dict[str, Any],
        desired: dict[str, Any],
    ) -> dict[str, Any]:
        if not _template_needs_update(template, desired):
            return template
        dataset_id = template.get("id")
        if not dataset_id:
            return template
        payload = {
            key: desired[key]
            for key in ("description", "permission", "chunk_method", "parser_config")
            if key in desired
        }
        updated = self.ragflow_client.update_dataset(str(dataset_id), payload)
        self.log.info(
            "ragflow.template_dataset.updated",
            template_dataset_name=self.template_dataset_name,
            dataset_id=dataset_id,
        )
        return updated

    @staticmethod
    def library_slug(library_name: str) -> str:
        return slugify(library_name)


def _template_needs_update(template: dict[str, Any], desired: dict[str, Any]) -> bool:
    for key in ("description", "permission", "chunk_method", "parser_config"):
        if key not in desired:
            continue
        actual = template.get(key)
        expected = desired[key]
        if isinstance(expected, dict):
            if not isinstance(actual, dict) or not _mapping_contains(actual, expected):
                return True
            continue
        if actual != expected:
            return True
    return False


def _mapping_contains(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if isinstance(expected_value, dict):
            if not isinstance(actual_value, dict) or not _mapping_contains(
                actual_value,
                expected_value,
            ):
                return False
            continue
        if actual_value != expected_value:
            return False
    return True
