"""Small provider-neutral request/result surface for structured generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field


class StorySceneOutput(BaseModel):
    order: int
    narration: str
    visual_keywords: list[str] = Field(min_length=1, max_length=10)
    visual_direction: str | None = None


class SuggestedMetadataOutput(BaseModel):
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class StoryOutput(BaseModel):
    title: str
    language: str
    narration: str
    scenes: list[StorySceneOutput] = Field(min_length=1, max_length=100)
    suggested_metadata: SuggestedMetadataOutput


@dataclass(frozen=True, slots=True)
class LlmCapabilities:
    structured_output: bool
    usage_reporting: bool = True
    request_id: bool = True
    native_retry: bool = False


@dataclass(frozen=True, slots=True)
class LlmRequest:
    system_instruction: str
    user_content: str
    response_schema: type[BaseModel]
    model: str
    temperature: float
    max_output_tokens: int
    timeout_seconds: float
    request_key: str


@dataclass(frozen=True, slots=True)
class LlmResult:
    provider: str
    model: str
    structured_data: dict[str, Any]
    finish_reason: str
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    completed: bool = True
    refused: bool = False


class LlmProvider(Protocol):
    name: str
    capabilities: LlmCapabilities

    async def generate(self, request: LlmRequest) -> LlmResult: ...
