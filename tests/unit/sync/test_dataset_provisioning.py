from __future__ import annotations

import unittest
from typing import Any

from seafile_ragflow_connector.domain.naming import build_dataset_name
from seafile_ragflow_connector.sync.dataset_provisioning import (
    DatasetProvisioner,
    DatasetProvisioningError,
    LibrarySource,
)


class _FakeRAGFlowClient:
    def __init__(
        self,
        dataset: dict[str, Any],
        *,
        update_response: dict[str, Any] | None = None,
    ) -> None:
        self.dataset = dataset
        self.update_response = update_response
        self.updated_datasets: list[tuple[str, dict[str, Any]]] = []

    def list_datasets(
        self,
        *,
        name: str | None = None,
        parse_status: str | None = None,
    ) -> list[dict[str, Any]]:
        _ = name, parse_status
        return [self.dataset]

    def update_dataset(
        self,
        dataset_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.updated_datasets.append((dataset_id, payload))
        if self.update_response is not None:
            return self.update_response
        return {**self.dataset, **payload}


class DatasetProvisionerPermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.library = LibrarySource(repo_id="repo-1", name="Demo")
        self.dataset_name = build_dataset_name(self.library.name, self.library.repo_id)

    def _provisioner(
        self,
        client: _FakeRAGFlowClient,
        *,
        permission: str = "team",
    ) -> DatasetProvisioner:
        return DatasetProvisioner(
            client,  # type: ignore[arg-type]
            template_auto_create=False,
            template_required=False,
            generated_dataset_permission=permission,  # type: ignore[arg-type]
        )

    def test_existing_dataset_permission_is_upgraded_from_me_to_team(self) -> None:
        parser_config = {"chunk_token_num": 777, "layout_recognize": "DeepDOC"}
        dataset = {
            "id": "dataset-1",
            "name": self.dataset_name,
            "permission": "me",
            "chunk_method": "naive",
            "parser_config": parser_config,
            "description": "Existing description",
        }
        client = _FakeRAGFlowClient(dataset)

        result = self._provisioner(client).ensure_dataset(self.library)

        self.assertFalse(result.created)
        self.assertEqual(client.updated_datasets, [("dataset-1", {"permission": "team"})])
        self.assertEqual(result.settings_payload["permission"], "team")
        self.assertEqual(result.settings_payload["parser_config"], parser_config)
        self.assertEqual(result.settings_payload["chunk_method"], "naive")
        self.assertEqual(result.settings_payload["description"], "Existing description")

    def test_existing_dataset_with_desired_permission_is_not_updated(self) -> None:
        dataset = {
            "id": "dataset-1",
            "name": self.dataset_name,
            "permission": "team",
            "parser_config": {"chunk_token_num": 777},
        }
        client = _FakeRAGFlowClient(dataset)

        result = self._provisioner(client).ensure_dataset(self.library)

        self.assertFalse(result.created)
        self.assertEqual(client.updated_datasets, [])
        self.assertIs(result.settings_payload, dataset)

    def test_permission_update_response_is_verified_fail_closed(self) -> None:
        dataset = {
            "id": "dataset-1",
            "name": self.dataset_name,
            "permission": "me",
            "parser_config": {"chunk_token_num": 777},
        }
        client = _FakeRAGFlowClient(
            dataset,
            update_response={
                "id": "dataset-1",
                "name": self.dataset_name,
                "permission": "me",
            },
        )

        with self.assertRaisesRegex(
            DatasetProvisioningError,
            "permission update returned an unexpected response",
        ):
            self._provisioner(client).ensure_dataset(self.library)

        self.assertEqual(client.updated_datasets, [("dataset-1", {"permission": "team"})])

    def test_non_matching_dataset_is_not_updated(self) -> None:
        client = _FakeRAGFlowClient(
            {
                "id": "foreign-dataset",
                "name": "Manual knowledge base",
                "permission": "me",
            }
        )

        with self.assertRaisesRegex(
            DatasetProvisioningError,
            "template dataset not found",
        ):
            self._provisioner(client).ensure_dataset(self.library)

        self.assertEqual(client.updated_datasets, [])


if __name__ == "__main__":
    unittest.main()
