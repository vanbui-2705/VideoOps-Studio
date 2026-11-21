"""Transactional PostgreSQL repository for versioned channel profiles."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.adapters.persistence.channel_mappers import (
    channel_draft_from_dict,
    channel_draft_to_dict,
)
from core.adapters.persistence.models import (
    AuditEntryRow,
    ChannelProfileRevisionRow,
    ChannelProfileRow,
)
from core.application.ports import ChannelSnapshot
from core.domain.channel_models import ChannelDraft, ChannelProfile
from core.domain.errors import (
    ChannelAlreadyExists,
    ChannelProfileNotFound,
    ChannelRevisionConflict,
)
from core.domain.models import Platform


class PostgresChannelRepository:
    """Store current profile state and append every committed revision atomically."""

    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def list(self) -> tuple[ChannelProfile, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ChannelProfileRow).order_by(
                    ChannelProfileRow.name, ChannelProfileRow.channel_id
                )
            ).all()
            return tuple(self._project(row) for row in rows)

    def get(self, channel_id: str) -> ChannelProfile | None:
        with self._sessions() as session:
            row = session.get(ChannelProfileRow, channel_id)
            return self._project(row) if row else None

    def get_snapshot(self, channel_id: str) -> ChannelSnapshot | None:
        profile = self.get(channel_id)
        if profile is None or not profile.draft.enabled:
            return None
        refs = profile.draft.credential_refs
        targets: list[Platform] = []
        if refs.youtube_secret_ref:
            targets.append(Platform.YOUTUBE)
        if refs.tiktok_secret_ref:
            targets.append(Platform.TIKTOK)
        return ChannelSnapshot(
            profile.draft.channel_id,
            profile.draft.name,
            profile.revision,
            tuple(targets),
        )

    def get_revision(self, channel_id: str, revision: int) -> ChannelProfile | None:
        with self._sessions() as session:
            history = session.scalar(
                select(ChannelProfileRevisionRow).where(
                    ChannelProfileRevisionRow.channel_id == channel_id,
                    ChannelProfileRevisionRow.revision == revision,
                )
            )
            if history is None:
                return None
            current = session.get(ChannelProfileRow, channel_id)
            if current is None:
                return None
            return ChannelProfile(
                draft=channel_draft_from_dict(history.profile_snapshot),
                revision=history.revision,
                created_at=current.created_at,
                updated_at=history.changed_at,
            )

    def save(
        self,
        draft: ChannelDraft,
        expected_revision: int | None,
        now: datetime,
        *,
        actor_id: str | None = None,
        change_reason: str | None = None,
    ) -> ChannelProfile:
        snapshot = channel_draft_to_dict(draft)
        try:
            with self._sessions.begin() as session:
                row = session.scalar(
                    select(ChannelProfileRow)
                    .where(ChannelProfileRow.channel_id == draft.channel_id)
                    .with_for_update()
                )
                if row is None:
                    if expected_revision is not None:
                        raise ChannelProfileNotFound(draft.channel_id)
                    profile = ChannelProfile(draft, 1, now, now)
                    row = ChannelProfileRow(
                        channel_id=draft.channel_id,
                        name=draft.name,
                        niche=draft.niche,
                        language=draft.language,
                        revision=1,
                        enabled=draft.enabled,
                        profile_snapshot=snapshot,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                    session.flush()
                    action = "CHANNEL_PROFILE_CREATED"
                else:
                    if expected_revision is None:
                        raise ChannelAlreadyExists(draft.channel_id)
                    if row.revision != expected_revision:
                        raise ChannelRevisionConflict(draft.channel_id)
                    revision = row.revision + 1
                    profile = ChannelProfile(draft, revision, row.created_at, now)
                    row.name = draft.name
                    row.niche = draft.niche
                    row.language = draft.language
                    row.revision = revision
                    row.enabled = draft.enabled
                    row.profile_snapshot = snapshot
                    row.updated_at = now
                    action = "CHANNEL_PROFILE_UPDATED"

                session.add(
                    ChannelProfileRevisionRow(
                        channel_id=draft.channel_id,
                        revision=profile.revision,
                        profile_snapshot=snapshot,
                        changed_at=now,
                        actor_id=actor_id,
                        # Free-form reasons are withheld until authenticated actor
                        # input has a dedicated redaction policy.
                        change_reason=None,
                    )
                )
                session.add(
                    AuditEntryRow(
                        job_id=None,
                        actor_type="ADMIN",
                        actor_id=actor_id,
                        action=action,
                        audit_metadata={
                            "channel_id": draft.channel_id,
                            "revision": profile.revision,
                            "groups": ["profile"],
                        },
                        created_at=now,
                    )
                )
        except IntegrityError as exc:
            if expected_revision is None:
                raise ChannelAlreadyExists(draft.channel_id) from exc
            raise
        return profile

    @staticmethod
    def _project(row: ChannelProfileRow) -> ChannelProfile:
        return ChannelProfile(
            draft=channel_draft_from_dict(row.profile_snapshot),
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
