from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

import structlog
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.clients.seafile_admin import SeafileAdminClient
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.domain.naming import slugify
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.search import (
    LibraryACLEffectiveUser,
    LibraryACLSubject,
    SearchProfile,
)
from seafile_ragflow_connector.sync.discovery import normalize_library, should_skip_library

Permission = Literal["r", "rw", "admin"]
Decision = Literal["allow", "deny"]

_PERMISSION_RANK: dict[str, int] = {"r": 1, "rw": 2, "admin": 3}
_DEFAULT_SERVICE: AccessControlService | None = None


class _AccessControlConfig(Protocol):
    authz_api_fail_closed: bool
    authz_api_max_acl_age_seconds: int


@dataclass(frozen=True)
class UserIdentity:
    username: str | None
    email: str | None


@dataclass(frozen=True)
class AuthzResource:
    repo_id: str | None
    ragflow_dataset_id: str | None


@dataclass(frozen=True)
class AuthzDecision:
    decision: Decision
    repo_id: str | None
    ragflow_dataset_id: str | None
    permission: str | None
    reason: str
    acl_version: str | None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "decision": self.decision,
            "repo_id": self.repo_id,
            "ragflow_dataset_id": self.ragflow_dataset_id,
            "reason": self.reason,
            "acl_version": self.acl_version,
        }
        if self.permission:
            payload["permission"] = self.permission
        return payload


@dataclass(frozen=True)
class ACLRefreshSummary:
    libraries_seen: int = 0
    libraries_refreshed: int = 0
    libraries_failed: int = 0
    effective_users: int = 0


@dataclass(frozen=True)
class _RawACLSubject:
    subject_type: str
    subject_id: str
    subject_name: str | None
    permission: Permission
    source: str


@dataclass(frozen=True)
class _EffectiveGrant:
    user_email: str
    permission: Permission
    sources: tuple[str, ...]


class ACLSnapshotService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        admin_client: SeafileAdminClient,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.admin_client = admin_client
        self.log = structlog.get_logger(__name__)
        self._user_contact_email_by_email: dict[str, str] | None = None

    def refresh_once(self) -> ACLRefreshSummary:
        now = _utcnow()
        self._user_contact_email_by_email = None
        summary = ACLRefreshSummary()
        for raw_library in self.admin_client.iter_libraries():
            summary = ACLRefreshSummary(
                libraries_seen=summary.libraries_seen + 1,
                libraries_refreshed=summary.libraries_refreshed,
                libraries_failed=summary.libraries_failed,
                effective_users=summary.effective_users,
            )
            library = normalize_library(raw_library)
            skipped, reason = should_skip_library(
                library,
                skip_encrypted=self.settings.seafile_skip_encrypted_libraries,
                skip_virtual=self.settings.seafile_skip_virtual_repos,
            )
            if skipped:
                self._mark_profile_disabled(library.repo_id, library.name, f"skipped:{reason}", now)
                continue
            try:
                raw_subjects, effective_grants = self._collect_library_acl(raw_library, now)
                refreshed_users = self._write_library_acl(
                    repo_id=library.repo_id,
                    display_name=library.name,
                    raw_subjects=raw_subjects,
                    effective_grants=effective_grants,
                    now=now,
                )
            except Exception as exc:
                summary = ACLRefreshSummary(
                    libraries_seen=summary.libraries_seen,
                    libraries_refreshed=summary.libraries_refreshed,
                    libraries_failed=summary.libraries_failed + 1,
                    effective_users=summary.effective_users,
                )
                self._mark_profile_failed(library.repo_id, library.name, str(exc), now)
                self.log.warning(
                    "acl_snapshot.library_failed",
                    repo_id=library.repo_id,
                    error=str(exc),
                )
                continue
            summary = ACLRefreshSummary(
                libraries_seen=summary.libraries_seen,
                libraries_refreshed=summary.libraries_refreshed + 1,
                libraries_failed=summary.libraries_failed,
                effective_users=summary.effective_users + refreshed_users,
            )
        return summary

    def _collect_library_acl(
        self,
        raw_library: dict[str, Any],
        now: datetime,
    ) -> tuple[list[_RawACLSubject], list[_EffectiveGrant]]:
        _ = now
        library = normalize_library(raw_library)
        subjects: list[_RawACLSubject] = []
        effective: dict[str, tuple[Permission, set[str]]] = {}

        owner = normalize_email(library.owner_email)
        if owner:
            subjects.append(
                _RawACLSubject(
                    subject_type="owner",
                    subject_id=owner,
                    subject_name=library.owner_email,
                    permission="admin",
                    source="seafile_owner",
                )
            )
            _merge_effective(effective, owner, "admin", "owner")

        for share in self.admin_client.list_library_shares(library.repo_id, share_type="user"):
            user_email = self._shared_user_email(share)
            if not user_email:
                continue
            permission = _normalize_permission(_first_text(share, "permission", "perm"))
            subjects.append(
                _RawACLSubject(
                    subject_type="user",
                    subject_id=user_email,
                    subject_name=_first_text(share, "user_name", "name", "username"),
                    permission=permission,
                    source="seafile_user_share",
                )
            )
            _merge_effective(effective, user_email, permission, "user_share")

        for share in self.admin_client.list_library_shares(library.repo_id, share_type="group"):
            group_id = _first_text(share, "group_id", "id", "share_to", "group")
            if not group_id:
                continue
            permission = _normalize_permission(_first_text(share, "permission", "perm"))
            subjects.append(
                _RawACLSubject(
                    subject_type="group",
                    subject_id=group_id,
                    subject_name=_first_text(share, "group_name", "name"),
                    permission=permission,
                    source="seafile_group_share",
                )
            )
            for member in self.admin_client.list_group_members(group_id):
                user_email = self._shared_user_email(member)
                if user_email:
                    _merge_effective(effective, user_email, permission, f"group:{group_id}")

        grants = [
            _EffectiveGrant(user_email=email, permission=permission, sources=tuple(sorted(sources)))
            for email, (permission, sources) in sorted(effective.items())
        ]
        return subjects, grants

    def _shared_user_email(self, raw: dict[str, Any]) -> str | None:
        contact_email = normalize_email(_first_text(raw, "contact_email", "user_contact_email"))
        if contact_email:
            return contact_email
        raw_email = normalize_email(_first_text(raw, "user_email", "email", "share_to", "user"))
        if raw_email:
            return self._user_contact_email_map().get(raw_email, raw_email)
        return normalize_email(_first_text(raw, "name", "username"))

    def _user_contact_email_map(self) -> dict[str, str]:
        if self._user_contact_email_by_email is not None:
            return self._user_contact_email_by_email
        mapping: dict[str, str] = {}
        iter_users = getattr(self.admin_client, "iter_users", None)
        if not callable(iter_users):
            self._user_contact_email_by_email = mapping
            return mapping
        for raw_user in iter_users():
            email = normalize_email(_first_text(raw_user, "email", "user_email"))
            contact_email = normalize_email(
                _first_text(raw_user, "contact_email", "user_contact_email")
            )
            if email and contact_email:
                mapping[email] = contact_email
        self._user_contact_email_by_email = mapping
        return mapping

    def _write_library_acl(
        self,
        *,
        repo_id: str,
        display_name: str,
        raw_subjects: list[_RawACLSubject],
        effective_grants: list[_EffectiveGrant],
        now: datetime,
    ) -> int:
        with self.session_factory() as session:
            self._upsert_profile(session, repo_id, display_name, now, status="ready", error=None)
            current_subject_keys = {
                (item.subject_type, item.subject_id, item.source)
                for item in raw_subjects
            }
            for raw_subject in raw_subjects:
                subject = session.scalar(
                    select(LibraryACLSubject).where(
                        LibraryACLSubject.repo_id == repo_id,
                        LibraryACLSubject.subject_type == raw_subject.subject_type,
                        LibraryACLSubject.subject_id == raw_subject.subject_id,
                        LibraryACLSubject.source == raw_subject.source,
                    )
                )
                if subject is None:
                    subject = LibraryACLSubject(
                        repo_id=repo_id,
                        subject_type=raw_subject.subject_type,
                        subject_id=raw_subject.subject_id,
                        source=raw_subject.source,
                        permission=raw_subject.permission,
                        last_seen_at=now,
                    )
                    session.add(subject)
                subject.subject_name = raw_subject.subject_name
                subject.permission = raw_subject.permission
                subject.last_seen_at = now

            stale_subjects = session.scalars(
                select(LibraryACLSubject).where(LibraryACLSubject.repo_id == repo_id)
            ).all()
            for subject in stale_subjects:
                key = (subject.subject_type, subject.subject_id, subject.source)
                if key not in current_subject_keys:
                    session.delete(subject)

            current_user_emails = {grant.user_email for grant in effective_grants}
            for grant in effective_grants:
                row = session.scalar(
                    select(LibraryACLEffectiveUser).where(
                        LibraryACLEffectiveUser.repo_id == repo_id,
                        LibraryACLEffectiveUser.user_email == grant.user_email,
                    )
                )
                if row is None:
                    row = LibraryACLEffectiveUser(
                        repo_id=repo_id,
                        user_email=grant.user_email,
                        permission=grant.permission,
                        sources=list(grant.sources),
                        last_seen_at=now,
                    )
                    session.add(row)
                row.permission = grant.permission
                row.sources = list(grant.sources)
                row.last_seen_at = now

            stale_users = session.scalars(
                select(LibraryACLEffectiveUser).where(
                    LibraryACLEffectiveUser.repo_id == repo_id
                )
            ).all()
            for row in stale_users:
                if row.user_email not in current_user_emails:
                    session.delete(row)
            session.commit()
        return len(effective_grants)

    def _mark_profile_disabled(
        self,
        repo_id: str,
        display_name: str,
        status: str,
        now: datetime,
    ) -> None:
        with self.session_factory() as session:
            self._upsert_profile(session, repo_id, display_name, now, status=status, error=None)
            session.commit()

    def _mark_profile_failed(
        self,
        repo_id: str,
        display_name: str,
        error: str,
        now: datetime,
    ) -> None:
        with self.session_factory() as session:
            self._upsert_profile(
                session,
                repo_id,
                display_name,
                now,
                status="failed",
                error=error[:4000],
            )
            session.commit()

    def _upsert_profile(
        self,
        session: Session,
        repo_id: str,
        display_name: str,
        now: datetime,
        *,
        status: str,
        error: str | None,
    ) -> SearchProfile:
        profile = session.scalar(select(SearchProfile).where(SearchProfile.repo_id == repo_id))
        library = session.get(Library, repo_id)
        dataset_id = library.ragflow_dataset_id if library else None
        dataset_name = library.ragflow_dataset_name if library else None
        if profile is None:
            profile = SearchProfile(
                repo_id=repo_id,
                display_name=display_name,
                kind=_guess_profile_kind(display_name),
                enabled=True,
                status=status,
            )
            session.add(profile)
        profile.display_name = display_name
        profile.description = f"Seafile-Bibliothek {display_name}"
        profile.ragflow_dataset_id = dataset_id
        profile.ragflow_dataset_name = dataset_name
        profile.kind = profile.kind or _guess_profile_kind(display_name)
        profile.enabled = status == "ready"
        profile.status = "pending" if status == "ready" and not dataset_id else status
        profile.last_acl_sync_at = None if status == "failed" else now
        profile.last_error = error
        if dataset_id:
            profile.last_dataset_sync_at = library.updated_at if library else now
        return profile


class AccessControlService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        fail_closed: bool = True,
        max_acl_age_seconds: int = 7200,
    ) -> None:
        self.session_factory = session_factory
        self.fail_closed = fail_closed
        self.max_acl_age = timedelta(seconds=max_acl_age_seconds)

    @classmethod
    def from_settings(
        cls,
        *,
        session_factory: sessionmaker[Session],
        settings: _AccessControlConfig,
    ) -> AccessControlService:
        return cls(
            session_factory=session_factory,
            fail_closed=settings.authz_api_fail_closed,
            max_acl_age_seconds=settings.authz_api_max_acl_age_seconds,
        )

    def resolve_repo_id(self, resource: AuthzResource) -> str | None:
        with self.session_factory() as session:
            profile = self._profile_for_resource(session, resource)
            return profile.repo_id if profile else None

    def check_access(
        self,
        user: UserIdentity,
        resource: AuthzResource,
        operation: str,
    ) -> AuthzDecision:
        username = normalize_username(user.username)
        email = normalize_email(user.email)
        if email is None and username and "@" in username:
            email = normalize_email(username)
        if operation != "search":
            return _deny(resource, "unsupported_operation")
        if not email and not username:
            return _deny(resource, "user_identity_missing")
        with self.session_factory() as session:
            profile = self._profile_for_resource(session, resource)
            if profile is None:
                return _deny(resource, "resource_not_found")
            resolved_resource = AuthzResource(
                repo_id=profile.repo_id,
                ragflow_dataset_id=profile.ragflow_dataset_id,
            )
            if not profile.ragflow_dataset_id:
                return _deny(resolved_resource, "dataset_mapping_missing")
            if not profile.enabled or profile.status != "ready":
                return _deny(resolved_resource, "profile_not_ready", _acl_version(profile))
            acl_version = _acl_version(profile)
            if self.fail_closed and acl_version is None:
                return _deny(resolved_resource, "acl_unknown", acl_version)
            if self.fail_closed and _profile_acl_stale(profile, self.max_acl_age):
                return _deny(resolved_resource, "acl_too_old", acl_version)
            grant, deny_reason = self._grant_for_identity(
                session,
                repo_id=profile.repo_id,
                email=email,
                username=username,
            )
            if grant is None:
                if (
                    deny_reason != "ambiguous_username"
                    and not self.fail_closed
                    and acl_version is None
                ):
                    return AuthzDecision(
                        decision="allow",
                        repo_id=profile.repo_id,
                        ragflow_dataset_id=profile.ragflow_dataset_id,
                        permission="r",
                        reason="fail_open_acl_unavailable",
                        acl_version=acl_version,
                    )
                return _deny(
                    resolved_resource,
                    deny_reason or "user_not_in_library_acl",
                    acl_version,
                )
            return AuthzDecision(
                decision="allow",
                repo_id=profile.repo_id,
                ragflow_dataset_id=profile.ragflow_dataset_id,
                permission=grant.permission,
                reason="effective_user_acl",
                acl_version=_iso_utc(grant.last_seen_at) or acl_version,
            )

    def filter_profiles_for_user(
        self,
        user: UserIdentity,
        profile_ids: list[str] | None,
    ) -> tuple[list[SearchProfile], list[dict[str, Any]]]:
        with self.session_factory() as session:
            query = select(SearchProfile).where(SearchProfile.enabled.is_(True))
            if profile_ids:
                query = _profile_ids_clause(query, profile_ids)
            rows = session.scalars(query.order_by(SearchProfile.display_name.asc())).all()
            allowed: list[SearchProfile] = []
            denied: list[dict[str, Any]] = []
            seen_requested = {row.repo_id for row in rows}
            seen_requested.update(str(row.ragflow_dataset_id or "") for row in rows)
            for row in rows:
                decision = self.check_access(
                    user,
                    AuthzResource(repo_id=row.repo_id, ragflow_dataset_id=row.ragflow_dataset_id),
                    "search",
                )
                if decision.decision == "allow":
                    session.expunge(row)
                    allowed.append(row)
                else:
                    denied.append(
                        {
                            "profile_id": row.repo_id,
                            "repo_id": row.repo_id,
                            "ragflow_dataset_id": row.ragflow_dataset_id,
                            "reason": decision.reason,
                        }
                    )
            for requested in profile_ids or []:
                if requested not in seen_requested:
                    denied.append(
                        {
                            "profile_id": requested,
                            "repo_id": requested,
                            "reason": "profile_not_found",
                        }
                    )
            return allowed, denied

    def _grant_for_identity(
        self,
        session: Session,
        *,
        repo_id: str,
        email: str | None,
        username: str | None,
    ) -> tuple[LibraryACLEffectiveUser | None, str | None]:
        direct_candidates: list[str] = []
        if email:
            direct_candidates.append(email)
        if username and "@" in username:
            username_email = normalize_email(username)
            if username_email and username_email not in direct_candidates:
                direct_candidates.append(username_email)
        for candidate in direct_candidates:
            grant = session.scalar(
                select(LibraryACLEffectiveUser).where(
                    LibraryACLEffectiveUser.repo_id == repo_id,
                    LibraryACLEffectiveUser.user_email == candidate,
                )
            )
            if grant is not None:
                return grant, None

        if email is None and username and "@" not in username:
            rows = session.scalars(
                select(LibraryACLEffectiveUser).where(
                    LibraryACLEffectiveUser.repo_id == repo_id
                )
            ).all()
            local_matches = [
                row for row in rows if _email_local_part(row.user_email) == username
            ]
            if len(local_matches) == 1:
                return local_matches[0], None
            if len(local_matches) > 1:
                return None, "ambiguous_username"

        return None, "user_not_in_library_acl"

    def _profile_for_resource(
        self,
        session: Session,
        resource: AuthzResource,
    ) -> SearchProfile | None:
        clauses = []
        if resource.repo_id:
            clauses.append(SearchProfile.repo_id == resource.repo_id)
        if resource.ragflow_dataset_id:
            clauses.append(SearchProfile.ragflow_dataset_id == resource.ragflow_dataset_id)
        if not clauses:
            return None
        return session.scalar(select(SearchProfile).where(or_(*clauses)).limit(1))


def configure_access_control(service: AccessControlService) -> None:
    global _DEFAULT_SERVICE
    _DEFAULT_SERVICE = service


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def normalize_username(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def resolve_repo_id(resource: AuthzResource) -> str | None:
    return _default_service().resolve_repo_id(resource)


def check_access(user: UserIdentity, resource: AuthzResource, operation: str) -> AuthzDecision:
    return _default_service().check_access(user, resource, operation)


def filter_profiles_for_user(
    user: UserIdentity,
    profile_ids: list[str] | None,
) -> tuple[list[SearchProfile], list[dict[str, Any]]]:
    return _default_service().filter_profiles_for_user(user, profile_ids)


def _default_service() -> AccessControlService:
    if _DEFAULT_SERVICE is None:
        msg = "access control service is not configured"
        raise RuntimeError(msg)
    return _DEFAULT_SERVICE


def _profile_ids_clause(
    query: Select[tuple[SearchProfile]],
    profile_ids: list[str],
) -> Select[tuple[SearchProfile]]:
    normalized = [str(item).strip() for item in profile_ids if str(item).strip()]
    if not normalized:
        return query
    return query.where(
        or_(
            SearchProfile.repo_id.in_(normalized),
            SearchProfile.ragflow_dataset_id.in_(normalized),
        )
    )


def _deny(
    resource: AuthzResource,
    reason: str,
    acl_version: str | None = None,
) -> AuthzDecision:
    return AuthzDecision(
        decision="deny",
        repo_id=resource.repo_id,
        ragflow_dataset_id=resource.ragflow_dataset_id,
        permission=None,
        reason=reason,
        acl_version=acl_version,
    )


def _merge_effective(
    grants: dict[str, tuple[Permission, set[str]]],
    user_email: str,
    permission: Permission,
    source: str,
) -> None:
    current = grants.get(user_email)
    if current is None:
        grants[user_email] = (permission, {source})
        return
    current_permission, current_sources = current
    if _PERMISSION_RANK[permission] > _PERMISSION_RANK[current_permission]:
        grants[user_email] = (permission, {*current_sources, source})
        return
    current_sources.add(source)


def _normalize_permission(value: str | None) -> Permission:
    normalized = str(value or "r").strip().lower()
    if normalized in {"admin", "cloud-edit", "owner"}:
        return "admin"
    if normalized in {"rw", "read-write", "read_write", "write", "w"}:
        return "rw"
    return "r"


def _first_text(raw: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _email_local_part(value: str) -> str | None:
    normalized = normalize_email(value)
    if not normalized or "@" not in normalized:
        return None
    return normalized.split("@", 1)[0] or None


def _guess_profile_kind(name: str) -> str:
    value = slugify(name, fallback="library")
    if "wiki" in value:
        return "wiki"
    if "pdf" in value:
        return "pdf"
    if "doc" in value or "dokument" in value:
        return "documents"
    return "library"


def _profile_acl_stale(profile: SearchProfile, max_age: timedelta) -> bool:
    if profile.last_acl_sync_at is None:
        return True
    return _utcnow() - _ensure_aware(profile.last_acl_sync_at) > max_age


def _acl_version(profile: SearchProfile) -> str | None:
    return _iso_utc(profile.last_acl_sync_at)


def _iso_utc(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_aware(value).isoformat(timespec="seconds").replace("+00:00", "Z")
    return str(value)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def delete_acl_for_missing_repos(
    session_factory: sessionmaker[Session],
    current_repo_ids: Iterable[str],
) -> None:
    current = set(current_repo_ids)
    with session_factory() as session:
        missing = session.scalars(
            select(SearchProfile.repo_id).where(SearchProfile.repo_id.not_in(current))
        ).all()
        for repo_id in missing:
            session.execute(
                delete(LibraryACLSubject).where(LibraryACLSubject.repo_id == repo_id)
            )
            session.execute(
                delete(LibraryACLEffectiveUser).where(
                    LibraryACLEffectiveUser.repo_id == repo_id
                )
            )
            profile = session.scalar(select(SearchProfile).where(SearchProfile.repo_id == repo_id))
            if profile:
                profile.enabled = False
                profile.status = "disabled"
        session.commit()


def latest_acl_version(session: Session) -> str | None:
    value = session.scalar(select(func.max(SearchProfile.last_acl_sync_at)))
    return _iso_utc(value)
