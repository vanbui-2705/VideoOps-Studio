"""Lossless JSON serialization for generated story drafts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.domain.story_models import (
    ScriptDraft,
    ScriptProvenance,
    ScriptScene,
    StorySource,
    SuggestedMetadata,
)


def story_to_dict(draft: ScriptDraft) -> dict[str, Any]:
    provenance = draft.provenance
    return {
        "language": draft.language,
        "title": draft.title,
        "narration": draft.narration,
        "scenes": [
            {
                "order": scene.order,
                "narration": scene.narration,
                "visual_keywords": list(scene.visual_keywords),
                "visual_direction": scene.visual_direction,
            }
            for scene in draft.scenes
        ],
        "suggested_metadata": {
            "title": draft.suggested_metadata.title,
            "description": draft.suggested_metadata.description,
            "tags": list(draft.suggested_metadata.tags),
        },
        "provenance": {
            "source": provenance.source.value,
            "prompt_version": provenance.prompt_version,
            "prompt_hash": provenance.prompt_hash,
            "input_hash": provenance.input_hash,
            "generated_at": provenance.generated_at.isoformat(),
            "provider": provenance.provider,
            "model": provenance.model,
            "provider_request_id": provenance.provider_request_id,
            "input_tokens": provenance.input_tokens,
            "output_tokens": provenance.output_tokens,
        },
    }


def story_from_dict(data: dict[str, Any]) -> ScriptDraft:
    provenance = data["provenance"]
    metadata = data["suggested_metadata"]
    return ScriptDraft(
        language=data["language"],
        title=data["title"],
        narration=data["narration"],
        scenes=tuple(
            ScriptScene(
                order=scene["order"],
                narration=scene["narration"],
                visual_keywords=tuple(scene["visual_keywords"]),
                visual_direction=scene.get("visual_direction"),
            )
            for scene in data["scenes"]
        ),
        suggested_metadata=SuggestedMetadata(
            title=metadata["title"],
            description=metadata.get("description", ""),
            tags=tuple(metadata.get("tags", ())),
        ),
        provenance=ScriptProvenance(
            source=StorySource(provenance["source"]),
            prompt_version=provenance["prompt_version"],
            prompt_hash=provenance["prompt_hash"],
            input_hash=provenance["input_hash"],
            generated_at=datetime.fromisoformat(provenance["generated_at"]),
            provider=provenance.get("provider"),
            model=provenance.get("model"),
            provider_request_id=provenance.get("provider_request_id"),
            input_tokens=provenance.get("input_tokens"),
            output_tokens=provenance.get("output_tokens"),
        ),
    )
