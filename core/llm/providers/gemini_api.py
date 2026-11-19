"""Native Google Gen AI structured-output adapter."""

from __future__ import annotations

import json
from typing import Any

from google.genai import errors, types
from pydantic import BaseModel

from core.llm.contracts import LlmCapabilities, LlmRequest, LlmResult
from core.llm.errors import (
    LlmAuthenticationError,
    LlmInvalidResponse,
    LlmPermissionError,
    LlmRateLimited,
    LlmTimeout,
    LlmTransientError,
)


class GeminiApiProvider:
    name = "gemini"
    capabilities = LlmCapabilities(structured_output=True)

    def __init__(self, client: Any) -> None:
        self._client = client

    async def generate(self, request: LlmRequest) -> LlmResult:
        try:
            response = await self._client.models.generate_content(
                model=request.model,
                contents=request.user_content,
                config=types.GenerateContentConfig(
                    system_instruction=request.system_instruction,
                    response_mime_type="application/json",
                    response_schema=request.response_schema,
                    temperature=request.temperature,
                    max_output_tokens=request.max_output_tokens,
                ),
            )
        except TimeoutError as exc:
            raise LlmTimeout() from exc
        except errors.APIError as exc:
            raise _map_api_error(getattr(exc, "code", 500)) from exc
        except Exception as exc:
            raise LlmTransientError() from exc

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, BaseModel):
            data = parsed.model_dump(mode="json")
        elif isinstance(parsed, dict):
            data = parsed
        else:
            try:
                data = json.loads(response.text)
            except (TypeError, ValueError, AttributeError) as exc:
                raise LlmInvalidResponse() from exc
        candidates = getattr(response, "candidates", None) or ()
        finish = (
            _enum_text(getattr(candidates[0], "finish_reason", None))
            if candidates
            else "STOP"
        )
        usage = getattr(response, "usage_metadata", None)
        return LlmResult(
            provider=self.name,
            model=request.model,
            structured_data=data,
            finish_reason=finish,
            provider_request_id=getattr(response, "response_id", None),
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            completed=finish.upper() not in {"MAX_TOKENS", "MALFORMED_FUNCTION_CALL"},
            refused=finish.upper() in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"},
        )

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()


def _map_api_error(status: int):
    if status == 401:
        return LlmAuthenticationError()
    if status == 403:
        return LlmPermissionError()
    if status == 429:
        return LlmRateLimited()
    if status in {408, 504}:
        return LlmTimeout()
    return LlmTransientError() if status >= 500 else LlmInvalidResponse()


def _enum_text(value: Any) -> str:
    return str(getattr(value, "name", getattr(value, "value", value or "STOP")))
