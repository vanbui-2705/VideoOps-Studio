from datetime import UTC, datetime

import pytest

from core.domain.errors import DomainValidationError
from core.domain.story_models import (
    ScriptDraft,
    ScriptProvenance,
    ScriptScene,
    StorySource,
    SuggestedMetadata,
    validate_story_limits,
)


def _provenance(source: StorySource = StorySource.USER_SCRIPT) -> ScriptProvenance:
    return ScriptProvenance(
        source=source,
        prompt_version="story-v1",
        prompt_hash="a" * 64,
        input_hash="b" * 64,
        generated_at=datetime(2026, 11, 17, tzinfo=UTC),
        provider="gemini" if source is StorySource.LLM else None,
        model="configured-model" if source is StorySource.LLM else None,
    )


def test_story_draft_normalizes_keywords_and_validates_scene_order() -> None:
    draft = ScriptDraft(
        language="vi-VN",
        title="AI Story",
        narration="Đây là một kịch bản đủ dài để kiểm tra.",
        scenes=(
            ScriptScene(1, "Cảnh đầu", ("AI", "ai", "Data Center")),
            ScriptScene(2, "Cảnh sau", ("Future",)),
        ),
        suggested_metadata=SuggestedMetadata("AI Story", "Mô tả", ("AI",)),
        provenance=_provenance(),
    )

    assert draft.scenes[0].visual_keywords == ("AI", "Data Center")
    validate_story_limits(draft, min_characters=10, max_characters=1000)


def test_invalid_story_content_and_provenance_are_rejected() -> None:
    with pytest.raises(DomainValidationError):
        ScriptDraft(
            "vi-VN",
            "Title",
            "Narration",
            (ScriptScene(2, "Scene", ("keyword",)),),
            SuggestedMetadata("Title"),
            _provenance(),
        )
    with pytest.raises(DomainValidationError):
        ScriptProvenance(
            source=StorySource.LLM,
            prompt_version="v1",
            prompt_hash="a" * 64,
            input_hash="b" * 64,
            generated_at=datetime(2026, 11, 17, tzinfo=UTC),
        )


def test_story_limits_reject_short_or_oversized_content() -> None:
    draft = ScriptDraft(
        "vi-VN",
        "Title",
        "Short",
        (ScriptScene(1, "Short", ("test",)),),
        SuggestedMetadata("Title"),
        _provenance(),
    )

    with pytest.raises(DomainValidationError):
        validate_story_limits(draft, min_characters=10, max_characters=100)
