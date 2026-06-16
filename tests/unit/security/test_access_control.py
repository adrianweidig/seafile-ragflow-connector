from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.persistence.db import Base
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.search import (
    LibraryACLEffectiveUser,
    SearchProfile,
)
from seafile_ragflow_connector.security.access_control import (
    AccessControlService,
    ACLSnapshotService,
    AuthzResource,
    UserIdentity,
    normalize_email,
)


class AccessControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-anleitungen",
                    owner_email="bernd@example.local",
                    name="Anleitungen",
                    name_slug="anleitungen",
                    status="active",
                    ragflow_dataset_id="dataset-anleitungen",
                    ragflow_dataset_name="Anleitungen",
                )
            )
            session.commit()

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_acl_snapshot_expands_owner_users_groups_and_highest_permission_wins(self) -> None:
        service = ACLSnapshotService(
            settings=_settings(),
            session_factory=self.session_factory,
            admin_client=_FakeSeafileAdminClient(),
        )

        summary = service.refresh_once()

        self.assertEqual(summary.libraries_refreshed, 1)
        with self.session_factory() as session:
            grants = {
                row.user_email: row.permission
                for row in session.query(LibraryACLEffectiveUser).all()
            }
            self.assertEqual(grants["bernd@example.local"], "admin")
            self.assertEqual(grants["olaf@example.local"], "rw")
            self.assertEqual(grants["hugo@example.local"], "r")
            self.assertEqual(grants["carla@example.local"], "rw")
            self.assertEqual(grants["dan@example.local"], "rw")
            profile = session.query(SearchProfile).one()
            self.assertEqual(profile.status, "ready")

    def test_removed_share_disappears_after_acl_refresh(self) -> None:
        admin_client = _FakeSeafileAdminClient()
        service = ACLSnapshotService(
            settings=_settings(),
            session_factory=self.session_factory,
            admin_client=admin_client,
        )
        service.refresh_once()
        admin_client.user_shares = []

        service.refresh_once()

        with self.session_factory() as session:
            grants = {
                row.user_email: row.permission
                for row in session.query(LibraryACLEffectiveUser).all()
            }
            self.assertNotIn("hugo@example.local", grants)

    def test_group_member_error_marks_profile_failed(self) -> None:
        admin_client = _FakeSeafileAdminClient()
        admin_client.raise_group_error = True
        service = ACLSnapshotService(
            settings=_settings(),
            session_factory=self.session_factory,
            admin_client=admin_client,
        )

        summary = service.refresh_once()

        self.assertEqual(summary.libraries_failed, 1)
        with self.session_factory() as session:
            profile = session.query(SearchProfile).one()
            self.assertEqual(profile.status, "failed")
            self.assertIn("group failed", profile.last_error or "")

    def test_authz_allows_olaf_denies_alfred_and_maps_dataset_id(self) -> None:
        ACLSnapshotService(
            settings=_settings(),
            session_factory=self.session_factory,
            admin_client=_FakeSeafileAdminClient(),
        ).refresh_once()
        service = AccessControlService(session_factory=self.session_factory)

        allowed = service.check_access(
            UserIdentity(username="olaf", email="OLAF@EXAMPLE.LOCAL"),
            AuthzResource(repo_id=None, ragflow_dataset_id="dataset-anleitungen"),
            "search",
        )
        denied = service.check_access(
            UserIdentity(username="alfred", email="alfred@example.local"),
            AuthzResource(repo_id="repo-anleitungen", ragflow_dataset_id=None),
            "search",
        )

        self.assertEqual(normalize_email(" OLAF@EXAMPLE.LOCAL "), "olaf@example.local")
        self.assertEqual(allowed.decision, "allow")
        self.assertEqual(allowed.repo_id, "repo-anleitungen")
        self.assertEqual(allowed.permission, "rw")
        self.assertEqual(denied.decision, "deny")
        self.assertEqual(denied.reason, "user_not_in_library_acl")

    def test_authz_denies_missing_mail_and_unknown_dataset_fail_closed(self) -> None:
        ACLSnapshotService(
            settings=_settings(),
            session_factory=self.session_factory,
            admin_client=_FakeSeafileAdminClient(),
        ).refresh_once()
        service = AccessControlService(session_factory=self.session_factory)

        missing_user = service.check_access(
            UserIdentity(username="unknown", email=None),
            AuthzResource(repo_id="repo-anleitungen", ragflow_dataset_id=None),
            "search",
        )
        unknown_dataset = service.check_access(
            UserIdentity(username="olaf", email="olaf@example.local"),
            AuthzResource(repo_id=None, ragflow_dataset_id="missing-dataset"),
            "search",
        )

        self.assertEqual(missing_user.decision, "deny")
        self.assertEqual(missing_user.reason, "user_identity_missing")
        self.assertEqual(unknown_dataset.decision, "deny")
        self.assertEqual(unknown_dataset.reason, "resource_not_found")


def _settings() -> Settings:
    return Settings(
        seafile_base_url="http://seafile.local",
        seafile_admin_token="admin-token",
        seafile_sync_user_token="sync-token",
        ragflow_base_url="http://ragflow.local",
        ragflow_api_key="ragflow-token",
        database_url="sqlite://",
        redis_url="redis://127.0.0.1:1/0",
    )


class _FakeSeafileAdminClient:
    raise_group_error = False

    def __init__(self) -> None:
        self.user_shares = [
            {"user_email": "olaf@example.local", "permission": "rw"},
            {"user_email": "hugo@example.local", "permission": "r"},
        ]

    def iter_libraries(self) -> list[dict[str, object]]:
        return [
            {
                "id": "repo-anleitungen",
                "name": "Anleitungen",
                "owner": "bernd@example.local",
            }
        ]

    def list_library_shares(self, repo_id: str, *, share_type: str) -> list[dict[str, object]]:
        self.assert_repo(repo_id)
        if share_type == "user":
            return list(self.user_shares)
        return [{"group_id": "42", "group_name": "Team", "permission": "rw"}]

    def list_group_members(self, group_id: str) -> list[dict[str, object]]:
        if self.raise_group_error:
            raise RuntimeError("group failed")
        self.assertEqual(group_id, "42")
        return [{"email": "carla@example.local"}, {"email": "dan@example.local"}]

    def assert_repo(self, repo_id: str) -> None:
        if repo_id != "repo-anleitungen":
            raise AssertionError(repo_id)

    def assertEqual(self, left: object, right: object) -> None:
        if left != right:
            raise AssertionError(f"{left!r} != {right!r}")


if __name__ == "__main__":
    unittest.main()
