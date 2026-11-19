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
from core.application.preview_service import (
    PreviewPreparationConfig,
    PreviewPreparationService,
)
from core.application.story_service import StoryScriptService, StoryServiceConfig
from core.application.video_workflow import DefaultWorkflowProcessor
from core.domain.models import WorkKind
from core.llm.contracts import LlmProvider
from core.llm.errors import LlmConfigurationError
from core.runtime.preview_handler import PreviewRenderHandler
from core.runtime.story_handler import StoryPreparationHandler
from core.runtime.worker import Worker


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


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


def build_preview_worker(config: AppConfig) -> PreviewWorkerRuntime:
    """Compose a worker that only leases story preview rendering work."""
    if not config.DATABASE_URL:
        raise ValueError("DATABASE_URL is required for the preview worker")
    validate_media_runtime(config)
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
    required_tables = {
        "jobs",
        "work_items",
        "artifacts",
        "channel_profile_revisions",
        "story_generations",
    }
    available_tables = set(sqlalchemy_inspect(engine).get_table_names())
    missing_tables = required_tables - available_tables
    if missing_tables:
        engine.dispose()
        raise ValueError("Database migrations are not at the required revision")
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
    service = PreviewPreparationService(
        tts=EdgeTtsProvider(
            connect_timeout_seconds=config.TTS_CONNECT_TIMEOUT_SECONDS,
            receive_timeout_seconds=config.TTS_RECEIVE_TIMEOUT_SECONDS,
        ),
        stock_providers=tuple(providers),
        downloader=BoundedStockDownloader(
            client, max_bytes=config.STOCK_MAX_DOWNLOAD_BYTES
        ),
        probe=FfprobeMediaProbe(
            config.FFPROBE_BINARY,
            timeout_seconds=min(config.PREVIEW_RENDER_TIMEOUT_SECONDS, 60),
        ),
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
    handler = PreviewRenderHandler(workflow_store, channels, service)
    worker = Worker(
        worker_id=f"{config.WORKER_ID}-preview",
        queue=queue,
        processor=DefaultWorkflowProcessor(workflow_store, SystemClock()),
        handlers={WorkKind.RENDER_PREVIEW: handler},
        lease_seconds=config.WORK_LEASE_SECONDS,
        poll_interval_seconds=config.WORK_POLL_INTERVAL_SECONDS,
    )
    return PreviewWorkerRuntime(worker, client, engine)
