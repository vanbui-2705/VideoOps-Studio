"""Native OpenAI Responses structured-output adapter."""

from __future__ import annotations

from typing import Any

import openai
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


class OpenAIApiProvider:
    name = "openai"
    capabilities = LlmCapabilities(structured_output=True)

    def __init__(self, client: Any) -> None:
        self._client = client

    async def generate(self, request: LlmRequest) -> LlmResult:
        try:
            response = await self._client.responses.parse(
                model=request.model,
                instructions=request.system_instruction,
                input=request.user_content,
                text_format=request.response_schema,
                max_output_tokens=request.max_output_tokens,
                temperature=request.temperature,
                prompt_cache_key=request.request_key,
                store=False,
                timeout=request.timeout_seconds,
            )
        except openai.AuthenticationError as exc:
            raise LlmAuthenticationError() from exc
        except openai.PermissionDeniedError as exc:
            raise LlmPermissionError() from exc
        except openai.RateLimitError as exc:
            raise LlmRateLimited() from exc
        except openai.APITimeoutError as exc:
            raise LlmTimeout() from exc
        except (openai.APIConnectionError, openai.InternalServerError) as exc:
            raise LlmTransientError() from exc
        except openai.APIStatusError as exc:
            raise _map_status(exc.status_code) from exc
        except Exception as exc:
            raise LlmInvalidResponse() from exc

        parsed = getattr(response, "output_parsed", None)
        refused = _has_refusal(getattr(response, "output", ()))
        if isinstance(parsed, BaseModel):
            data = parsed.model_dump(mode="json")
        elif isinstance(parsed, dict):
            data = parsed
        else:
            data = {}
        status = str(getattr(response, "status", "completed"))
        usage = getattr(response, "usage", None)
        return LlmResult(
            provider=self.name,
            model=request.model,
            structured_data=data,
            finish_reason=status.upper(),
            provider_request_id=getattr(response, "id", None),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            completed=status == "completed" and bool(data),
            refused=refused,
        )

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()


def _has_refusal(outputs: Any) -> bool:
    for output in outputs or ():
        for content in getattr(output, "content", ()) or ():
            if getattr(content, "type", None) == "refusal":
                return True
    return False


def _map_status(status: int):
    if status == 401:
        return LlmAuthenticationError()
    if status == 403:
        return LlmPermissionError()
    if status == 429:
        return LlmRateLimited()
    return LlmTransientError() if status >= 500 else LlmInvalidResponse()
