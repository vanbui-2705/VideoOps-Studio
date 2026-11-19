"""Normalized safe errors shared by all LLM providers."""

from __future__ import annotations


class LlmError(Exception):
    code = "LLM_ERROR"
    retryable = False

    def __init__(
        self,
        message: str = "Language model request failed",
        *,
        retry_after: float | None = None,
        diagnostic_ref: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.diagnostic_ref = diagnostic_ref


class LlmConfigurationError(LlmError):
    code = "LLM_CONFIGURATION"


class LlmAuthenticationError(LlmError):
    code = "LLM_AUTHENTICATION"


class LlmPermissionError(LlmError):
    code = "LLM_PERMISSION"


class LlmRateLimited(LlmError):
    code = "LLM_RATE_LIMITED"
    retryable = True


class LlmTimeout(LlmError):
    code = "LLM_TIMEOUT"
    retryable = True


class LlmTransientError(LlmError):
    code = "LLM_TRANSIENT"
    retryable = True


class LlmRefusal(LlmError):
    code = "LLM_REFUSAL"


class LlmOutputTruncated(LlmError):
    code = "LLM_OUTPUT_TRUNCATED"


class LlmInvalidResponse(LlmError):
    code = "LLM_INVALID_RESPONSE"


class StoryGenerationConflict(LlmError):
    code = "STORY_GENERATION_CONFLICT"
