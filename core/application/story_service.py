"""Prepare deterministic user scripts or validated structured LLM stories."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError

from core.domain.channel_models import ChannelProfile
from core.domain.models import StorySnapshot, VideoMetadata
from core.domain.story_models import (
    ScriptDraft,
    ScriptProvenance,
    ScriptScene,
    StorySource,
    SuggestedMetadata,
    validate_story_limits,
)
from core.llm.contracts import LlmProvider, LlmRequest, StoryOutput
from core.llm.errors import (
    LlmConfigurationError,
    LlmError,
    LlmInvalidResponse,
    LlmOutputTruncated,
    LlmRefusal,
    LlmTimeout,
)


@dataclass(frozen=True, slots=True)
class StoryServiceConfig:
    model: str
    prompt_version: str
    min_characters: int
    max_characters: int
    max_scenes: int
    max_keywords_per_scene: int
    max_attempts: int
    timeout_seconds: float
    max_output_tokens: int
    temperature: float


@dataclass(frozen=True, slots=True)
class PrepareStoryRequest:
    job_id: str
    content_revision: int
    story: StorySnapshot
    channel: ChannelProfile
    metadata: VideoMetadata
    regeneration_instructions: tuple[str, ...]


class StoryScriptService:
    def __init__(
        self,
        provider: LlmProvider | None,
        config: StoryServiceConfig,
        *,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._sleeper = sleeper
        self._random = random_value
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def provider(self) -> LlmProvider | None:
        return self._provider

    def request_hash(self, request: PrepareStoryRequest) -> str:
        base = story_request_hash(request)
        policy = {
            "base": base,
            "model": self._config.model,
            "prompt_version": self._config.prompt_version,
            "min_characters": self._config.min_characters,
            "max_characters": self._config.max_characters,
            "max_scenes": self._config.max_scenes,
            "max_keywords_per_scene": self._config.max_keywords_per_scene,
        }
        return _hash_text(json.dumps(policy, sort_keys=True))

    async def prepare(
        self,
        request: PrepareStoryRequest,
        heartbeat: Callable[[], None] | None = None,
    ) -> ScriptDraft:
        if request.story.script:
            return self._from_user_script(request)
        if self._provider is None or not self._config.model:
            raise LlmConfigurationError("LLM provider and model are not configured")
        return await self._from_prompt(request, heartbeat)

    def _from_user_script(self, request: PrepareStoryRequest) -> ScriptDraft:
        narration = request.story.script or ""
        paragraphs = tuple(
            paragraph.strip()
            for paragraph in narration.split("\n\n")
            if paragraph.strip()
        ) or (narration.strip(),)
        keywords = request.channel.draft.visual.stock_keywords or (
            request.channel.draft.niche,
        )
        input_hash = _hash_text(narration)
        draft = ScriptDraft(
            language=request.channel.draft.language,
            title=request.metadata.title or request.channel.name,
            narration=narration,
            scenes=tuple(
                ScriptScene(index, paragraph, keywords)
                for index, paragraph in enumerate(paragraphs, start=1)
            ),
            suggested_metadata=SuggestedMetadata(
                request.metadata.title or request.channel.name,
                request.metadata.description,
                request.metadata.tags,
            ),
            provenance=ScriptProvenance(
                source=StorySource.USER_SCRIPT,
                prompt_version=self._config.prompt_version,
                prompt_hash=_hash_text(f"user-script:{self._config.prompt_version}"),
                input_hash=input_hash,
                generated_at=self._now(),
            ),
        )
        self._validate(draft)
        return draft

    async def _from_prompt(
        self,
        request: PrepareStoryRequest,
        heartbeat: Callable[[], None] | None,
    ) -> ScriptDraft:
        assert request.story.prompt is not None
        system_instruction, user_content = self._build_prompt(request)
        prompt_hash = _hash_text(system_instruction + "\n" + user_content)
        llm_request = LlmRequest(
            system_instruction=system_instruction,
            user_content=user_content,
            response_schema=StoryOutput,
            model=self._config.model,
            temperature=self._config.temperature,
            max_output_tokens=self._config.max_output_tokens,
            timeout_seconds=self._config.timeout_seconds,
            request_key=f"{request.job_id}:{request.content_revision}:{prompt_hash}",
        )
        result = await self._generate_with_retry(llm_request, heartbeat)
        if result.refused:
            raise LlmRefusal("Language model refused the story request")
        if not result.completed or result.finish_reason.upper() in {
            "MAX_TOKENS",
            "LENGTH",
            "INCOMPLETE",
        }:
            raise LlmOutputTruncated("Language model output was incomplete")
        try:
            parsed = StoryOutput.model_validate(result.structured_data)
        except ValidationError as exc:
            raise LlmInvalidResponse(
                "Language model output failed schema validation"
            ) from exc
        draft = ScriptDraft(
            language=parsed.language,
            title=parsed.title,
            narration=parsed.narration,
            scenes=tuple(
                ScriptScene(
                    scene.order,
                    scene.narration,
                    tuple(scene.visual_keywords),
                    scene.visual_direction,
                )
                for scene in parsed.scenes
            ),
            suggested_metadata=SuggestedMetadata(
                parsed.suggested_metadata.title,
                parsed.suggested_metadata.description,
                tuple(parsed.suggested_metadata.tags),
            ),
            provenance=ScriptProvenance(
                source=StorySource.LLM,
                prompt_version=self._config.prompt_version,
                prompt_hash=prompt_hash,
                input_hash=_hash_text(request.story.prompt),
                generated_at=self._now(),
                provider=result.provider,
                model=result.model,
                provider_request_id=result.provider_request_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            ),
        )
        self._validate(draft)
        return draft

    async def _generate_with_retry(
        self,
        request: LlmRequest,
        heartbeat: Callable[[], None] | None,
    ):
        assert self._provider is not None
        for attempt in range(1, self._config.max_attempts + 1):
            try:
                return await asyncio.wait_for(
                    self._provider.generate(request),
                    timeout=self._config.timeout_seconds,
                )
            except TimeoutError as exc:
                error: LlmError = LlmTimeout()
                if attempt >= self._config.max_attempts:
                    raise error from exc
            except LlmError as exc:
                error = exc
                if not exc.retryable or attempt >= self._config.max_attempts:
                    raise
            if heartbeat:
                heartbeat()
            delay = max(error.retry_after or 0.0, 2 ** (attempt - 1) + self._random())
            await self._sleeper(delay)
        raise AssertionError("Retry loop did not terminate")

    def _build_prompt(self, request: PrepareStoryRequest) -> tuple[str, str]:
        profile = request.channel.draft
        rendered = profile.content.prompt_template.format(input=request.story.prompt)
        regeneration = "\n".join(request.regeneration_instructions) or "None"
        system = (
            "Create a structured video narration. Return only data matching the supplied schema. "
            f"Language: {profile.language}. Persona: {profile.content.persona}. "
            f"Tone: {profile.content.tone}. Niche: {profile.niche}. "
            "You have no tools, publishing authority, filesystem, environment, or credentials."
        )
        user = (
            "<story_request>\n"
            f"{rendered}\n"
            "</story_request>\n"
            "<regeneration_instructions>\n"
            f"{regeneration}\n"
            "</regeneration_instructions>"
        )
        return system, user

    def _validate(self, draft: ScriptDraft) -> None:
        validate_story_limits(
            draft,
            min_characters=self._config.min_characters,
            max_characters=self._config.max_characters,
            max_scenes=self._config.max_scenes,
            max_keywords_per_scene=self._config.max_keywords_per_scene,
        )


def story_request_hash(request: PrepareStoryRequest) -> str:
    payload = {
        "job_id": request.job_id,
        "content_revision": request.content_revision,
        "story": {
            "script": request.story.script,
            "prompt": request.story.prompt,
        },
        "channel_id": request.channel.channel_id,
        "channel_revision": request.channel.revision,
        "metadata": {
            "title": request.metadata.title,
            "description": request.metadata.description,
            "tags": request.metadata.tags,
            "category_id": request.metadata.category_id,
            "privacy": request.metadata.privacy,
        },
        "regeneration": request.regeneration_instructions,
    }
    return _hash_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
