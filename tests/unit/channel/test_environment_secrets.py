import pytest

from core.adapters.secrets.environment import EnvironmentSecretResolver
from core.domain.channel_models import CredentialReferences
from core.domain.errors import CredentialUnavailable
from core.domain.models import Platform

_MARKER = "VIDEOOPS_TEST_SECRET_9f37"


def test_complete_bundles_enable_targets_without_exposing_values() -> None:
    resolver = EnvironmentSecretResolver(
        {
            "YT_TECH_YOUTUBE_CLIENT_ID": "client-id",
            "YT_TECH_YOUTUBE_CLIENT_SECRET": _MARKER,
            "YT_TECH_YOUTUBE_REFRESH_TOKEN": "refresh-token",
            "TT_TECH_TIKTOK_ACCESS_TOKEN": _MARKER,
            "TT_TECH_TIKTOK_OPEN_ID": "creator-open-id",
        }
    )
    references = CredentialReferences("YT_TECH", "TT_TECH")

    status = resolver.status(references)
    youtube = resolver.resolve_youtube("YT_TECH")
    tiktok = resolver.resolve_tiktok("TT_TECH")

    assert status.available_targets == (Platform.YOUTUBE, Platform.TIKTOK)
    assert status.missing_youtube_fields == ()
    assert _MARKER not in repr(status)
    assert _MARKER not in repr(youtube)
    assert _MARKER not in repr(tiktok)


def test_partial_bundle_is_safe_and_unavailable() -> None:
    resolver = EnvironmentSecretResolver({"YT_TECH_YOUTUBE_CLIENT_ID": "only-id"})

    status = resolver.status(CredentialReferences(youtube_secret_ref="YT_TECH"))

    assert status.available_targets == ()
    assert status.missing_youtube_fields == (
        "YOUTUBE_CLIENT_SECRET",
        "YOUTUBE_REFRESH_TOKEN",
    )
    with pytest.raises(CredentialUnavailable, match="incomplete"):
        resolver.resolve_youtube("YT_TECH")
