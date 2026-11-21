"""Deep application module for safe, idempotent target publishing."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from core.adapters.media.workspace import JobWorkspace
from core.application.channel_ports import ChannelRepository, SecretResolver
from core.application.events import (
    TargetPublishFailed,
    TargetPublishStarted,
    TargetPublishSucceeded,
    TargetPublishUnknown,
    WorkflowEvent,
)
from core.application.media_ports import ArtifactManifestStore
from core.application.ports import DeferredWork, QueuedWork, WorkflowStore
from core.application.publish_attempts import PublishAttemptStatus, PublishAttemptStore
from core.application.publish_ports import (
    Publisher,
    PublishFailed,
    PublishProcessing,
    PublishRequest,
    PublishSucceeded,
    PublishUnknown,
    logical_publish_key,
)
from core.application.video_workflow import WorkflowProcessor
from core.domain.errors import DomainValidationError, UnsafeWorkspacePath
from core.domain.models import (
    ArtifactKind,
    JobFailure,
    JobPhase,
    JobStatus,
    Platform,
    ResumeAction,
    TargetStatus,
    WorkKind,
)


class PublishCoordinator:
    """Validate and publish one frozen target without leaking provider details."""

    def __init__(
        self,
        *,
        workflow_store: WorkflowStore,
        processor: WorkflowProcessor,
        channels: ChannelRepository,
        secrets: SecretResolver,
        manifests: ArtifactManifestStore,
        attempts: PublishAttemptStore,
        publishers: Mapping[Platform, Publisher],
        temp_root: Path,
        now: Callable[[], datetime] | None = None,
        max_status_polls: int = 120,
    ) -> None:
        if max_status_polls < 1:
            raise ValueError("max_status_polls must be positive")
        self._workflow_store = workflow_store
        self._processor = processor
        self._channels = channels
        self._secrets = secrets
        self._manifests = manifests
        self._attempts = attempts
        self._publishers = dict(publishers)
        self._temp_root = Path(temp_root)
        self._now = now or (lambda: datetime.now(UTC))
        self._max_status_polls = max_status_polls

    def execute(
        self, work: QueuedWork, heartbeat: Callable[[], None]
    ) -> WorkflowEvent | DeferredWork | None:
        return self._run(work, heartbeat, force_reconcile=False)

    def reconcile(
        self, work: QueuedWork, heartbeat: Callable[[], None]
    ) -> WorkflowEvent | DeferredWork | None:
        return self._run(work, heartbeat, force_reconcile=True)

    def _run(
        self,
        work: QueuedWork,
        heartbeat: Callable[[], None],
        *,
        force_reconcile: bool,
    ) -> WorkflowEvent | DeferredWork | None:
        job = self._workflow_store.get(work.intent.job_id)
        platform_value = work.intent.platform
        if (
            job is None
            or platform_value is None
            or work.intent.kind
            not in {WorkKind.PUBLISH_TARGET, WorkKind.RECONCILE_TARGET}
            or job.status is not JobStatus.PUBLISHING
            or job.content_revision != work.intent.content_revision
        ):
            return None
        platform: Platform = platform_value
        approval = job.approval_snapshot
        target = next(
            (item for item in job.publish_targets if item.platform is platform), None
        )
        if (
            approval is None
            or approval.content_revision != job.content_revision
            or approval.channel_revision != job.channel_revision
            or platform not in approval.target_platforms
            or target is None
            or target.status in {TargetStatus.SUCCEEDED, TargetStatus.SKIPPED}
        ):
            return None

        master = self._validated_master(job)
        if master is None:
            return self._failed_event(
                job.revision, platform, "PUBLISH_MASTER_INVALID", False
            )
        profile = self._channels.get_revision(job.channel_id, job.channel_revision)
        publisher = self._publishers.get(platform)
        if (
            profile is None
            or profile.draft.channel_id != job.channel_id
            or profile.revision != job.channel_revision
            or publisher is None
            or getattr(publisher, "platform", None) is not platform
        ):
            return self._failed_event(
                job.revision, platform, "PUBLISH_CONFIGURATION", False
            )
        try:
            credential = self._credential(profile, platform)
        except Exception:  # noqa: BLE001 - redact secret adapter failures
            return self._failed_event(
                job.revision, platform, "PUBLISH_CREDENTIAL_UNAVAILABLE", False
            )

        key = logical_publish_key(
            job.job_id, platform, job.content_revision, job.channel_revision
        )
        attempt = self._attempts.begin_or_get(
            job.job_id,
            platform,
            key,
            self._now(),
            restart=target.status is TargetStatus.FAILED,
        )
        request = PublishRequest(
            job_id=job.job_id,
            platform=platform,
            idempotency_key=key,
            master_path=master[0],
            master_checksum=master[1],
            master_size=master[2],
            metadata=approval.metadata,
            credential=credential,
            duration_ms=master[3],
        )

        should_reconcile = (
            force_reconcile
            or work.intent.kind is WorkKind.RECONCILE_TARGET
            or target.status in {TargetStatus.UPLOADING, TargetStatus.UNKNOWN}
            or attempt.status
            in {PublishAttemptStatus.PROCESSING, PublishAttemptStatus.UNKNOWN}
        )
        if (
            attempt.status is PublishAttemptStatus.SUCCEEDED
            and attempt.external_id
            and attempt.public_url
        ):
            return TargetPublishSucceeded(
                job.revision, platform, attempt.external_id, attempt.public_url
            )
        if not should_reconcile:
            self._processor.apply(
                job.job_id, TargetPublishStarted(job.revision, platform)
            )
            job = self._workflow_store.get(job.job_id)
            assert job is not None
            outcome = publisher.publish(request, heartbeat=heartbeat)
        else:
            outcome = publisher.reconcile(
                request,
                attempt.provider_operation_id,
                heartbeat=heartbeat,
            )
        current = self._workflow_store.get(job.job_id)
        assert current is not None
        return self._outcome_event(current.revision, platform, key, outcome, work)

    def _outcome_event(self, revision, platform, key, outcome, work):
        now = self._now()
        if isinstance(outcome, PublishSucceeded):
            receipt = outcome.receipt
            if not _trusted_public_url(platform, receipt.public_url):
                self._attempts.update(
                    key,
                    PublishAttemptStatus.FAILED,
                    now,
                    error_code="PUBLISH_RECEIPT_INVALID",
                )
                return self._failed_event(
                    revision, platform, "PUBLISH_RECEIPT_INVALID", False
                )
            self._attempts.update(
                key,
                PublishAttemptStatus.SUCCEEDED,
                now,
                provider_operation_id=receipt.provider_operation_id,
                external_id=receipt.external_video_id,
                public_url=receipt.public_url,
            )
            return TargetPublishSucceeded(
                revision,
                platform,
                receipt.external_video_id,
                receipt.public_url,
            )
        if isinstance(outcome, PublishProcessing):
            if work.attempts >= min(work.max_attempts, self._max_status_polls):
                self._attempts.update(
                    key,
                    PublishAttemptStatus.UNKNOWN,
                    now,
                    provider_operation_id=outcome.provider_operation_id,
                    error_code="PUBLISH_STATUS_TIMEOUT",
                )
                return TargetPublishUnknown(
                    revision, platform, "PUBLISH_STATUS_TIMEOUT"
                )
            self._attempts.update(
                key,
                PublishAttemptStatus.PROCESSING,
                now,
                provider_operation_id=outcome.provider_operation_id,
                retry_after=outcome.retry_at,
            )
            return DeferredWork(None, outcome.retry_at, "PUBLISH_PROCESSING")
        if isinstance(outcome, PublishUnknown):
            self._attempts.update(
                key,
                PublishAttemptStatus.UNKNOWN,
                now,
                provider_operation_id=outcome.provider_operation_id,
                error_code="PUBLISH_UNKNOWN",
            )
            return TargetPublishUnknown(revision, platform, outcome.diagnostic_ref)
        assert isinstance(outcome, PublishFailed)
        self._attempts.update(
            key,
            PublishAttemptStatus.FAILED,
            now,
            error_code=outcome.code,
            retry_after=outcome.retry_after,
        )
        return self._failed_event(
            revision,
            platform,
            outcome.code,
            outcome.retryable,
            outcome.retry_after,
        )

    def _validated_master(self, job) -> tuple[Path, str, int, int] | None:
        refs = [
            item
            for item in job.artifacts
            if item.kind is ArtifactKind.MASTER
            and item.content_revision == job.content_revision
        ]
        if len(refs) != 1:
            return None
        manifest = self._manifests.get(job.job_id, refs[0].artifact_id)
        if (
            manifest is None
            or manifest.job_id != job.job_id
            or manifest.artifact_id != refs[0].artifact_id
            or manifest.artifact_type != "MASTER"
            or manifest.content_revision != job.content_revision
            or manifest.media_info is None
            or manifest.media_info.codec != "h264"
            or not manifest.media_info.has_audio
            or manifest.media_info.audio_codec not in {None, "aac"}
            or (manifest.media_info.width, manifest.media_info.height)
            not in {(1920, 1080), (1080, 1920)}
        ):
            return None
        try:
            workspace = JobWorkspace(self._temp_root, job.job_id, job.content_revision)
            path = workspace.final_path(manifest.relative_path)
            if (
                not path.is_file()
                or path.stat().st_size != manifest.byte_size
                or _sha256(path) != manifest.checksum
            ):
                return None
        except (OSError, UnsafeWorkspacePath):
            return None
        return (
            path,
            manifest.checksum,
            manifest.byte_size,
            manifest.media_info.duration_ms,
        )

    def _credential(self, profile, platform):
        refs = profile.draft.credential_refs
        if platform is Platform.YOUTUBE:
            if not refs.youtube_secret_ref:
                raise DomainValidationError("YouTube credential reference is missing")
            return self._secrets.resolve_youtube(refs.youtube_secret_ref)
        if not refs.tiktok_secret_ref:
            raise DomainValidationError("TikTok credential reference is missing")
        return self._secrets.resolve_tiktok(refs.tiktok_secret_ref)

    @staticmethod
    def _failed_event(
        revision, platform, code, retryable, retry_after=None
    ) -> TargetPublishFailed:
        return TargetPublishFailed(
            revision,
            platform,
            JobFailure(
                code=code[:128],
                phase=JobPhase.PUBLISH,
                message_safe="Publishing failed. Check the target and retry.",
                retryable=retryable,
                resume_action=ResumeAction.PUBLISH,
                retry_after=retry_after,
                target_platform=platform,
            ),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_public_url(platform: Platform, value: str) -> bool:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme != "https":
        return False
    if platform is Platform.YOUTUBE:
        return hostname in {"youtube.com", "www.youtube.com", "youtu.be"}
    return hostname in {"tiktok.com", "www.tiktok.com"}
