"""Persistence seam for idempotent story generation results."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from core.domain.story_models import ScriptDraft


class StoryGenerationStore(Protocol):
    def get_completed(
        self, job_id: str, content_revision: int, request_hash: str
    ) -> ScriptDraft | None: ...

    def record_completed(
        self,
        job_id: str,
        content_revision: int,
        request_hash: str,
        draft: ScriptDraft,
        completed_at: datetime,
    ) -> ScriptDraft: ...
