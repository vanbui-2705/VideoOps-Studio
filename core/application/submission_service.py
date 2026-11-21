"""Narrow UI-facing facade for Story/Remix submission and safe refresh."""

from __future__ import annotations

from collections.abc import Sequence

from core.application.requests import RemixClip, RemixRequest, StoryRequest
from core.application.security import Action, AuthorizationPolicy, Principal
from core.application.video_workflow import VideoWorkflow
from core.application.views import JobView
from core.domain.errors import DomainValidationError
from core.domain.models import VideoMetadata


class JobSubmissionService:
    def __init__(
        self,
        workflow: VideoWorkflow,
        *,
        max_remix_clips: int = 10,
        principal: Principal | None = None,
        authorization: AuthorizationPolicy | None = None,
    ) -> None:
        if max_remix_clips < 1:
            raise ValueError("Remix clip limit must be positive")
        self._workflow = workflow
        self._max_remix_clips = max_remix_clips
        self._principal = principal
        self._authorization = authorization

    def submit_story(
        self,
        *,
        request_id: str,
        channel_id: str,
        source: str,
        content: str,
        metadata: VideoMetadata,
    ) -> JobView:
        self._require(Action.SUBMIT_JOB)
        self._validate_identity(request_id, channel_id, metadata)
        clean = content.strip()
        if not clean or source not in {"script", "prompt"}:
            raise DomainValidationError("Story source is invalid")
        request = StoryRequest(
            request_id=request_id.strip(),
            channel_id=channel_id.strip(),
            metadata=metadata,
            script=clean if source == "script" else None,
            prompt=clean if source == "prompt" else None,
        )
        return self._workflow.submit(request)

    def submit_remix(
        self,
        *,
        request_id: str,
        channel_id: str,
        rows: Sequence[Sequence[object]],
        copyright_confirmed: bool,
        metadata: VideoMetadata,
    ) -> JobView:
        self._require(Action.SUBMIT_JOB)
        self._validate_identity(request_id, channel_id, metadata)
        cleaned = tuple(row for row in rows if row and str(row[0]).strip())
        if len(cleaned) > self._max_remix_clips:
            raise DomainValidationError("Too many Remix clips")
        clips = tuple(self._clip(row, order) for order, row in enumerate(cleaned, 1))
        return self._workflow.submit(
            RemixRequest(
                request_id=request_id.strip(),
                channel_id=channel_id.strip(),
                clips=clips,
                copyright_confirmed=bool(copyright_confirmed),
                metadata=metadata,
            )
        )

    def get(self, job_id: str) -> JobView:
        self._require(Action.READ_JOB)
        clean = job_id.strip()
        if not clean:
            raise DomainValidationError("Job ID is required")
        return self._workflow.get(clean)

    @staticmethod
    def _clip(row: Sequence[object], order: int) -> RemixClip:
        if len(row) < 4:
            raise DomainValidationError("Remix row is incomplete")
        crop_mode = str(row[4]).strip().lower() if len(row) > 4 else "fill"
        mirror = bool(row[5]) if len(row) > 5 else False
        try:
            return RemixClip(
                url=str(row[0]).strip(),
                start_seconds=float(str(row[1])),
                end_seconds=float(str(row[2])),
                order=order,
                speed=float(str(row[3])),
                crop_mode=crop_mode,
                mirror=mirror,
            )
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("Remix row contains invalid numbers") from exc

    @staticmethod
    def _validate_identity(
        request_id: str, channel_id: str, metadata: VideoMetadata
    ) -> None:
        if (
            not request_id.strip()
            or not channel_id.strip()
            or not metadata.title.strip()
        ):
            raise DomainValidationError("Submission identity and title are required")

    def _require(self, action: Action) -> None:
        if self._authorization is not None and self._principal is not None:
            self._authorization.require(self._principal, action)
