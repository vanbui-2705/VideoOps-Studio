"""PostgreSQL-backed idempotency cache for prepared stories."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from core.adapters.persistence.models import StoryGenerationRow
from core.adapters.persistence.story_mappers import story_from_dict, story_to_dict
from core.domain.story_models import ScriptDraft
from core.llm.errors import StoryGenerationConflict


class PostgresStoryGenerationStore:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def get_completed(
        self, job_id: str, content_revision: int, request_hash: str
    ) -> ScriptDraft | None:
        with self._sessions() as session:
            row = session.scalar(
                select(StoryGenerationRow).where(
                    StoryGenerationRow.job_id == job_id,
                    StoryGenerationRow.content_revision == content_revision,
                )
            )
            if row is None:
                return None
            self._assert_hash(row, request_hash)
            return story_from_dict(row.result_snapshot)

    def record_completed(
        self,
        job_id: str,
        content_revision: int,
        request_hash: str,
        draft: ScriptDraft,
        completed_at: datetime,
    ) -> ScriptDraft:
        with self._sessions.begin() as session:
            session.execute(
                pg_insert(StoryGenerationRow)
                .values(
                    job_id=job_id,
                    content_revision=content_revision,
                    request_hash=request_hash,
                    result_snapshot=story_to_dict(draft),
                    completed_at=completed_at,
                )
                .on_conflict_do_nothing(constraint="uq_story_generation_revision")
            )
            row = session.scalar(
                select(StoryGenerationRow)
                .where(
                    StoryGenerationRow.job_id == job_id,
                    StoryGenerationRow.content_revision == content_revision,
                )
                .with_for_update()
            )
            assert row is not None
            self._assert_hash(row, request_hash)
            return story_from_dict(row.result_snapshot)

    @staticmethod
    def _assert_hash(row: StoryGenerationRow, request_hash: str) -> None:
        if row.request_hash != request_hash:
            raise StoryGenerationConflict(
                "Story inputs changed without a content revision change"
            )
