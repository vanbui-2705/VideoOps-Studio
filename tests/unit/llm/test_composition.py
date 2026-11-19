import pytest

from config import AppConfig
from core.composition import build_llm_provider, build_story_service
from core.llm.errors import LlmConfigurationError


def test_disabled_provider_keeps_user_script_path_available() -> None:
    service = build_story_service(AppConfig(LLM_PROVIDER="disabled"))

    assert service.provider is None


@pytest.mark.parametrize("provider", ["gemini", "openai"])
def test_enabled_provider_requires_model_before_api_key(provider: str) -> None:
    with pytest.raises(LlmConfigurationError, match="LLM_MODEL"):
        build_llm_provider(AppConfig(LLM_PROVIDER=provider))


def test_provider_allowlist_rejects_arbitrary_connector() -> None:
    with pytest.raises(LlmConfigurationError, match="LLM_PROVIDER"):
        build_llm_provider(
            AppConfig(LLM_PROVIDER="web-cookie-proxy", LLM_MODEL="model")
        )


def test_story_policy_validation_happens_at_composition() -> None:
    with pytest.raises(LlmConfigurationError, match="character limits"):
        build_story_service(
            AppConfig(STORY_MIN_CHARACTERS=1000, STORY_MAX_CHARACTERS=100)
        )
