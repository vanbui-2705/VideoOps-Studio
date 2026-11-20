"""Gradio entry point for NewVideo_Push."""

from config import load_config
from core.composition import build_channel_catalog, build_review_service
from ui.views import create_ui, launch_ui

__all__ = ["create_runtime_ui", "create_ui"]


def create_runtime_ui():
    """Build a preview-safe UI and opt into ChannelCatalog when configured."""
    config = load_config()
    channels = None
    review = None
    if config.DATABASE_URL:
        try:
            channels = build_channel_catalog(config)
            review = build_review_service(config)
        except Exception:  # noqa: BLE001 - startup fallback must redact backend details
            channels = None
            review = None
    return create_ui(
        channels=channels,
        review=review,
        channel_admin_enabled=config.CHANNEL_ADMIN_ENABLED,
    )


if __name__ == "__main__":
    launch_ui(create_runtime_ui())
