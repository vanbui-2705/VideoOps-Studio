from types import SimpleNamespace

import pytest

from core.llm.contracts import LlmRequest, StoryOutput
from core.llm.providers.gemini_api import GeminiApiProvider
from core.llm.providers.openai_api import OpenAIApiProvider


def _request() -> LlmRequest:
    return LlmRequest(
        "system",
        "user",
        StoryOutput,
        "configured-model",
        0.5,
        1000,
        30,
        "request-key",
    )


def _payload():
    return {
        "title": "Title",
        "language": "vi-VN",
        "narration": "Narration",
        "scenes": [
            {
                "order": 1,
                "narration": "Scene",
                "visual_keywords": ["keyword"],
                "visual_direction": None,
            }
        ],
        "suggested_metadata": {"title": "Title", "description": "", "tags": []},
    }


@pytest.mark.asyncio
async def test_gemini_adapter_normalizes_structured_response() -> None:
    response = SimpleNamespace(
        parsed=_payload(),
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=10, candidates_token_count=20
        ),
        response_id="gemini-request",
    )

    class Models:
        async def generate_content(self, **kwargs):
            return response

    result = await GeminiApiProvider(SimpleNamespace(models=Models())).generate(
        _request()
    )

    assert result.structured_data["title"] == "Title"
    assert result.input_tokens == 10
    assert result.provider_request_id == "gemini-request"


@pytest.mark.asyncio
async def test_openai_adapter_uses_responses_parsed_output() -> None:
    response = SimpleNamespace(
        output_parsed=StoryOutput.model_validate(_payload()),
        output=[],
        status="completed",
        id="openai-request",
        usage=SimpleNamespace(input_tokens=12, output_tokens=22),
    )

    class Responses:
        async def parse(self, **kwargs):
            return response

    result = await OpenAIApiProvider(SimpleNamespace(responses=Responses())).generate(
        _request()
    )

    assert result.structured_data["title"] == "Title"
    assert result.output_tokens == 22
    assert result.provider_request_id == "openai-request"
