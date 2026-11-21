from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.application.publish_ports import (
    PublishFailed,
    PublishReceipt,
    PublishRequest,
    PublishSucceeded,
    logical_publish_key,
)
from core.domain.errors import DomainValidationError
from core.domain.models import Platform, VideoMetadata


def test_logical_publish_key_is_stable_for_frozen_revision() -> None:
    assert logical_publish_key("job-1", Platform.YOUTUBE, 3, 7) == (
        "580107ffbf3a9f792b4ee671879eca24da8e96de0ca18e92e08ec6c7173ba4a0"
    )


def test_publish_contracts_reject_unconfirmed_or_unsafe_results() -> None:
    request = PublishRequest(
        job_id="job-1",
        platform=Platform.YOUTUBE,
        idempotency_key="a" * 64,
        master_path=Path("master.mp4"),
        master_checksum="b" * 64,
        master_size=10,
        metadata=VideoMetadata(title="Approved"),
        credential=object(),
    )
    assert request.metadata.title == "Approved"

    with pytest.raises(DomainValidationError):
        PublishSucceeded(
            PublishReceipt("", "https://youtube.com/watch?v=x", None, datetime.now(UTC))
        )
    with pytest.raises(DomainValidationError):
        PublishReceipt("video-1", "javascript:alert(1)", None, datetime.now(UTC))
    with pytest.raises(DomainValidationError):
        PublishFailed("", retryable=False)
