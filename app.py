"""Gradio entry point for NewVideo_Push."""

from config import load_config
from core.composition import (
    build_channel_catalog,
    build_review_service,
    build_submission_service,
    validate_security_settings,
)
from core.runtime.observability import configure_logging
from ui.views import create_ui, launch_ui

__all__ = ["create_runtime_ui", "create_ui"]


def create_runtime_ui(config=None):
    """Build a preview-safe UI and opt into ChannelCatalog when configured."""
    config = config or load_config()
    validate_security_settings(config)
    channels = None
    review = None
    submissions = None
    if config.DATABASE_URL:
        try:
            channels = build_channel_catalog(config)
            review = build_review_service(config)
            submissions = build_submission_service(config)
        except Exception:  # noqa: BLE001 - startup fallback must redact backend details
            channels = None
            review = None
            submissions = None
    return create_ui(
        workflow=submissions,
        channels=channels,
        review=review,
        channel_admin_enabled=config.CHANNEL_ADMIN_ENABLED,
    )


if __name__ == "__main__":
    configure_logging()
    runtime_config = load_config()
    authentication = None
    if runtime_config.DEPLOYMENT_MODE in {"private", "public"}:
        validate_security_settings(runtime_config)
        authentication = (
            runtime_config.APP_AUTH_USERNAME,
            runtime_config.APP_AUTH_PASSWORD,
        )
    launch_ui(create_runtime_ui(runtime_config), auth=authentication)
