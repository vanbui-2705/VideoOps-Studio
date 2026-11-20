"""Explicit runtime composition; imports and UI construction remain side-effect free."""

from __future__ import annotations

import inspect
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect as sqlalchemy_inspect

from config import AppConfig
from core.adapters.persistence import (
    PostgresArtifactManifestStore,
    PostgresChannelRepository,
    create_database_engine,
)
from core.adapters.persistence.story_generation_store import (
    PostgresStoryGenerationStore,
)
from core.adapters.persistence.work_queue import PostgresWorkQueue
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.adapters.secrets import EnvironmentSecretResolver
from core.application.channel_catalog import DefaultChannelCatalog
from core.application.master_service import MasterRenderConfig, MasterRenderService
from core.application.preview_service import (
    PreviewPreparationConfig,
    PreviewPreparationService,
)
from core.application.remix_service import RemixMediaConfig, RemixMediaService
from core.application.review_service import ReviewService
from core.application.story_service import StoryScriptService, StoryServiceConfig
from core.application.video_workflow import (
    DefaultVideoWorkflow,
    DefaultWorkflowProcessor,
)
from core.domain.models import WorkKind
from core.llm.contracts import LlmProvider
from core.llm.errors import LlmConfigurationError
from core.runtime.master_handler import MasterRenderHandler
from core.runtime.preview_handler import PreviewRenderHandler
from core.runtime.remix_handler import RemixPreparationHandler
from core.runtime.story_handler import StoryPreparationHandler
from core.runtime.worker import Worker


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SystemIds:
    def new_job_id(self) -> str:
        return f"job-{uuid4()}"


def build_review_service(config: AppConfig) -> ReviewService:
    """Compose the read/command facade consumed by the Review Gate UI."""
    if not config.DATABASE_URL:
        raise ValueError("DATABASE_URL is required for ReviewService")
    engine = create_database_engine(
        config.DATABASE_URL,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
    )
    store = PostgresWorkflowStore(engine, default_max_attempts=config.WORK_MAX_ATTEMPTS)
    workflow = DefaultVideoWorkflow(
        store,
        PostgresChannelRepository(engine),
        SystemClock(),
        SystemIds(),
    )
    return ReviewService(
        workflow,
        PostgresArtifactManifestStore(engine),
        config.TEMP_DIR,
    )


def build_channel_catalog(
    config: AppConfig,
    *,
    environment: Mapping[str, str] | None = None,
) -> DefaultChannelCatalog:
    """Compose Module 4 only when a PostgreSQL URL is explicitly configured."""
    if not config.DATABASE_URL:
        raise ValueError("DATABASE_URL is required for ChannelCatalog")
    engine = create_database_engine(
        config.DATABASE_URL,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
    )
    return DefaultChannelCatalog(
        PostgresChannelRepository(engine),
        EnvironmentSecretResolver(environment),
        SystemClock(),
        admin_enabled=config.CHANNEL_ADMIN_ENABLED,
    )


def build_llm_provider(config: AppConfig) -> LlmProvider | None:
    """Build one allowlisted native SDK adapter with SDK retries disabled."""
    provider = config.LLM_PROVIDER.strip().lower()
    if provider == "disabled":
        return None
    if not config.LLM_MODEL.strip():
        raise LlmConfigurationError("LLM_MODEL is required")
    if provider == "gemini":
        if not config.GEMINI_API_KEY:
            raise LlmConfigurationError("GEMINI_API_KEY is required")
        from google import genai
        from google.genai import types

        from core.llm.providers.gemini_api import GeminiApiProvider

        client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
        return GeminiApiProvider(client.aio)
    if provider == "openai":
        if not config.OPENAI_API_KEY:
            raise LlmConfigurationError("OPENAI_API_KEY is required")
        from openai import AsyncOpenAI

        from core.llm.providers.openai_api import OpenAIApiProvider

        return OpenAIApiProvider(
            AsyncOpenAI(api_key=config.OPENAI_API_KEY, max_retries=0)
        )
    raise LlmConfigurationError("LLM_PROVIDER must be disabled, gemini, or openai")


def build_story_service(config: AppConfig) -> StoryScriptService:
    if not 1 <= config.LLM_MAX_ATTEMPTS <= 10:
        raise LlmConfigurationError("LLM_MAX_ATTEMPTS must be between 1 and 10")
    if not 0 <= config.LLM_TEMPERATURE <= 2:
        raise LlmConfigurationError("LLM_TEMPERATURE must be between 0 and 2")
    if config.STORY_MIN_CHARACTERS > config.STORY_MAX_CHARACTERS:
        raise LlmConfigurationError("Story character limits are invalid")
    return StoryScriptService(
        build_llm_provider(config),
        StoryServiceConfig(
            model=config.LLM_MODEL,
            prompt_version=config.LLM_PROMPT_VERSION,
            min_characters=config.STORY_MIN_CHARACTERS,
            max_characters=config.STORY_MAX_CHARACTERS,
            max_scenes=config.STORY_MAX_SCENES,
            max_keywords_per_scene=config.STORY_MAX_KEYWORDS_PER_SCENE,
            max_attempts=config.LLM_MAX_ATTEMPTS,
            timeout_seconds=config.LLM_TIMEOUT_SECONDS,
            max_output_tokens=config.LLM_MAX_OUTPUT_TOKENS,
            temperature=config.LLM_TEMPERATURE,
        ),
    )


@dataclass(slots=True)
class StoryWorkerRuntime:
    worker: Worker
    provider: Any
    engine: Any

    def close(self) -> None:
        close = getattr(self.provider, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                self.worker.run_coroutine(result)
        self.worker.close()
        self.engine.dispose()


def build_story_worker(config: AppConfig) -> StoryWorkerRuntime:
    """Compose a worker that only leases PREPARE_STORY work."""
    if not config.DATABASE_URL:
        raise ValueError("DATABASE_URL is required for the story worker")
    engine = create_database_engine(
        config.DATABASE_URL,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
    )
    workflow_store = PostgresWorkflowStore(
        engine, default_max_attempts=config.WORK_MAX_ATTEMPTS
    )
    queue = PostgresWorkQueue(engine)
    channels = PostgresChannelRepository(engine)
    service = build_story_service(config)
    handler = StoryPreparationHandler(
        workflow_store,
        channels,
        service,
        PostgresStoryGenerationStore(engine),
    )
    worker = Worker(
        worker_id=config.WORKER_ID,
        queue=queue,
        processor=DefaultWorkflowProcessor(workflow_store, SystemClock()),
        handlers={WorkKind.PREPARE_STORY: handler},
        lease_seconds=config.WORK_LEASE_SECONDS,
        poll_interval_seconds=config.WORK_POLL_INTERVAL_SECONDS,
    )
    return StoryWorkerRuntime(worker, service.provider, engine)


@dataclass(slots=True)
class PreviewWorkerRuntime:
    worker: Worker
    http_client: Any
    engine: Any

    def close(self) -> None:
        try:
            self.worker.run_coroutine(self.http_client.aclose())
        finally:
            self.worker.close()
            self.engine.dispose()


def validate_media_runtime(config: AppConfig) -> None:
    """Fail before leasing work when required local media tools are unavailable."""
    for binary in (config.FFMPEG_BINARY, config.FFPROBE_BINARY):
        if shutil.which(binary) is None:
            raise ValueError(f"Required media binary is unavailable: {binary}")
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(dir=config.TEMP_DIR):
            pass
    except OSError as exc:
        raise ValueError("Preview temp directory is not writable") from exc
    free_gb = shutil.disk_usage(config.TEMP_DIR).free / (1024**3)
    if free_gb < config.MEDIA_MIN_FREE_DISK_GB:
        raise ValueError("Insufficient free disk for preview rendering")
    try:
        encoders = subprocess.run(
            [config.FFMPEG_BINARY, "-hide_banner", "-encoders"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
        filters = subprocess.run(
            [config.FFMPEG_BINARY, "-hide_banner", "-filters"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("FFmpeg capability check failed") from exc
    if "libx264" not in encoders or " aac " not in encoders:
        raise ValueError("FFmpeg requires libx264 and AAC encoders")
    if " subtitles " not in filters:
        raise ValueError("FFmpeg requires the subtitles filter")


def validate_remix_runtime(config: AppConfig) -> None:
    """Validate local binaries required before leasing PREPARE_REMIX work."""
    validate_media_runtime(config)
    if shutil.which(config.YTDLP_BINARY) is None:
        raise ValueError(f"Required remix binary is unavailable: {config.YTDLP_BINARY}")


def validate_master_settings(config: AppConfig) -> None:
    """Reject master profiles outside the bounded production policy."""
    if (
        config.MASTER_RENDER_TIMEOUT_SECONDS <= 0
        or config.MASTER_PRESET != "superfast"
        or not 0 <= config.MASTER_CRF <= 51
        or config.MASTER_DURATION_TOLERANCE_MS < 0
        or config.MAX_FFMPEG_THREADS > 2
        or config.MEDIA_RENDER_CONCURRENCY != 1
    ):
        raise ValueError("Master render settings are invalid")


def _require_worker_tables(engine: Any) -> None:
    required_tables = {
        "jobs",
        "work_items",
        "artifacts",
        "channel_profile_revisions",
        "story_generations",
    }
    available_tables = set(sqlalchemy_inspect(engine).get_table_names())
    if required_tables - available_tables:
        raise ValueError("Database migrations are not at the required revision")


def _build_remix_service(
    config: AppConfig,
    manifests: Any,
    probe: Any,
) -> RemixMediaService:
    from core.adapters.media.remix import (
        FfmpegRemixPreviewRenderer,
        FfmpegRemixProcessor,
        YtDlpSourceDownloader,
    )

    return RemixMediaService(
        downloader=YtDlpSourceDownloader(
            config.YTDLP_BINARY,
            timeout_seconds=config.REMIX_DOWNLOAD_TIMEOUT_SECONDS,
            max_bytes=config.REMIX_MAX_DOWNLOAD_BYTES,
        ),
        processor=FfmpegRemixProcessor(
            config.FFMPEG_BINARY,
            timeout_seconds=config.PREVIEW_RENDER_TIMEOUT_SECONDS,
        ),
        renderer=FfmpegRemixPreviewRenderer(
            config.FFMPEG_BINARY,
            timeout_seconds=config.PREVIEW_RENDER_TIMEOUT_SECONDS,
        ),
        probe=probe,
        manifests=manifests,
        config=RemixMediaConfig(
            temp_root=config.TEMP_DIR,
            assets_root=config.ASSETS_DIR,
            max_sources=config.REMIX_MAX_SOURCES,
            max_source_duration_seconds=config.REMIX_MAX_SOURCE_DURATION_SECONDS,
            duration_tolerance_ms=config.REMIX_DURATION_TOLERANCE_MS,
        ),
    )


def _build_master_service(
    config: AppConfig,
    manifests: Any,
    probe: Any,
) -> MasterRenderService:
    from core.adapters.media.ffmpeg_master import FfmpegMasterRenderer

    validate_master_settings(config)
    return MasterRenderService(
        renderer=FfmpegMasterRenderer(
            config.FFMPEG_BINARY,
            timeout_seconds=config.MASTER_RENDER_TIMEOUT_SECONDS,
        ),
        probe=probe,
        manifests=manifests,
        config=MasterRenderConfig(
            temp_root=config.TEMP_DIR,
            assets_root=config.ASSETS_DIR,
            duration_tolerance_ms=config.MASTER_DURATION_TOLERANCE_MS,
            preset=config.MASTER_PRESET,
            crf=config.MASTER_CRF,
        ),
    )


@dataclass(slots=True)
class RemixWorkerRuntime:
    worker: Worker
    engine: Any

    def close(self) -> None:
        self.worker.close()
        self.engine.dispose()


def build_remix_worker(config: AppConfig) -> RemixWorkerRuntime:
    """Compose a worker that only leases PREPARE_REMIX work."""
    if not config.DATABASE_URL:
        raise ValueError("DATABASE_URL is required for the remix worker")
    validate_remix_runtime(config)
    from core.adapters.media.ffmpeg_preview import FfprobeMediaProbe

    engine = create_database_engine(
        config.DATABASE_URL,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
    )
    try:
        _require_worker_tables(engine)
    except Exception:
        engine.dispose()
        raise
    workflow_store = PostgresWorkflowStore(
        engine, default_max_attempts=config.WORK_MAX_ATTEMPTS
    )
    queue = PostgresWorkQueue(engine)
    channels = PostgresChannelRepository(engine)
    manifests = PostgresArtifactManifestStore(engine)
    probe = FfprobeMediaProbe(
        config.FFPROBE_BINARY,
        timeout_seconds=min(config.PREVIEW_RENDER_TIMEOUT_SECONDS, 60),
    )
    service = _build_remix_service(config, manifests, probe)
    handler = RemixPreparationHandler(workflow_store, channels, service)
    worker = Worker(
        worker_id=f"{config.WORKER_ID}-remix",
        queue=queue,
        processor=DefaultWorkflowProcessor(workflow_store, SystemClock()),
        handlers={WorkKind.PREPARE_REMIX: handler},
        lease_seconds=config.WORK_LEASE_SECONDS,
        poll_interval_seconds=config.WORK_POLL_INTERVAL_SECONDS,
    )
    return RemixWorkerRuntime(worker, engine)


def build_preview_worker(config: AppConfig) -> PreviewWorkerRuntime:
    """Compose one serialized worker for preview and master rendering."""
    if not config.DATABASE_URL:
        raise ValueError("DATABASE_URL is required for the preview worker")
    validate_media_runtime(config)
    validate_master_settings(config)
    import httpx

    from core.adapters.media.edge_tts_provider import EdgeTtsProvider
    from core.adapters.media.ffmpeg_preview import (
        FfmpegPreviewRenderer,
        FfprobeMediaProbe,
    )
    from core.adapters.media.stock_http import (
        BoundedStockDownloader,
        PexelsStockProvider,
        PixabayStockProvider,
    )

    engine = create_database_engine(
        config.DATABASE_URL,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
    )
    try:
        _require_worker_tables(engine)
    except Exception:
        engine.dispose()
        raise
    workflow_store = PostgresWorkflowStore(
        engine, default_max_attempts=config.WORK_MAX_ATTEMPTS
    )
    channels = PostgresChannelRepository(engine)
    queue = PostgresWorkQueue(engine)
    manifests = PostgresArtifactManifestStore(engine)
    client = httpx.AsyncClient(
        timeout=config.STOCK_REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
    )
    providers = []
    if config.PEXELS_API_KEY:
        providers.append(PexelsStockProvider(config.PEXELS_API_KEY, client))
    if config.PIXABAY_API_KEY:
        providers.append(PixabayStockProvider(config.PIXABAY_API_KEY, client))
    probe = FfprobeMediaProbe(
        config.FFPROBE_BINARY,
        timeout_seconds=min(config.PREVIEW_RENDER_TIMEOUT_SECONDS, 60),
    )
    service = PreviewPreparationService(
        tts=EdgeTtsProvider(
            connect_timeout_seconds=config.TTS_CONNECT_TIMEOUT_SECONDS,
            receive_timeout_seconds=config.TTS_RECEIVE_TIMEOUT_SECONDS,
        ),
        stock_providers=tuple(providers),
        downloader=BoundedStockDownloader(
            client, max_bytes=config.STOCK_MAX_DOWNLOAD_BYTES
        ),
        probe=probe,
        renderer=FfmpegPreviewRenderer(
            config.FFMPEG_BINARY,
            timeout_seconds=config.PREVIEW_RENDER_TIMEOUT_SECONDS,
        ),
        manifests=manifests,
        config=PreviewPreparationConfig(
            temp_root=config.TEMP_DIR,
            duration_tolerance_ms=config.PREVIEW_DURATION_TOLERANCE_MS,
            assets_root=config.ASSETS_DIR,
            max_attempts=config.MEDIA_MAX_ATTEMPTS,
        ),
    )
    remix_service = _build_remix_service(config, manifests, probe)
    master_service = _build_master_service(config, manifests, probe)
    preview_handler = PreviewRenderHandler(
        workflow_store, channels, service, remix_service
    )
    master_handler = MasterRenderHandler(workflow_store, channels, master_service)
    worker = Worker(
        worker_id=f"{config.WORKER_ID}-preview",
        queue=queue,
        processor=DefaultWorkflowProcessor(workflow_store, SystemClock()),
        handlers={
            WorkKind.RENDER_PREVIEW: preview_handler,
            WorkKind.RENDER_MASTER: master_handler,
        },
        lease_seconds=config.WORK_LEASE_SECONDS,
        poll_interval_seconds=config.WORK_POLL_INTERVAL_SECONDS,
    )
    return PreviewWorkerRuntime(worker, client, engine)
