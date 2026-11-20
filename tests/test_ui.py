"""Public-interface tests for the Gradio application shell."""

import gradio as gr

from app import create_runtime_ui, create_ui


def test_create_ui_returns_blocks_without_dependencies() -> None:
    """The UI shell can be composed before production adapters exist."""
    demo = create_ui()

    assert isinstance(demo, gr.Blocks)


def test_runtime_ui_falls_back_when_channel_backend_configuration_is_invalid(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///unsafe.db")

    demo = create_runtime_ui()

    assert isinstance(demo, gr.Blocks)


def test_ui_exposes_the_four_operator_workspaces() -> None:
    """The v0 information architecture keeps each user journey reachable."""
    config = create_ui().get_config_file()
    tab_labels = {
        component["props"].get("label")
        for component in config["components"]
        if component["type"] == "tabitem"
    }

    assert tab_labels == {
        "AI Story",
        "Video Remix",
        "Review & Publish",
        "Channel & Credentials",
    }


class _EmptyCatalog:
    def list(self):
        return ()


def test_channel_workspace_never_renders_secret_value_input() -> None:
    config = create_ui(channels=_EmptyCatalog()).get_config_file()

    password_inputs = [
        component
        for component in config["components"]
        if component["type"] == "textbox"
        and component["props"].get("type") == "password"
    ]

    assert password_inputs == []


def test_channel_save_button_requires_explicit_admin_gate() -> None:
    readonly = create_ui(channels=_EmptyCatalog()).get_config_file()
    editable = create_ui(
        channels=_EmptyCatalog(), channel_admin_enabled=True
    ).get_config_file()

    def save_button(config):
        return next(
            component
            for component in config["components"]
            if component["type"] == "button"
            and component["props"].get("value") == "Save Channel Profile"
        )

    assert save_button(readonly)["props"]["interactive"] is False
    assert save_button(editable)["props"]["interactive"] is True


def test_review_actions_start_locked_and_cancel_remains_disabled() -> None:
    config = create_ui(review=object()).get_config_file()

    buttons = {
        component["props"].get("value"): component["props"].get("interactive")
        for component in config["components"]
        if component["type"] == "button"
    }

    assert buttons["Tải / Làm mới"] is True
    assert buttons["Lưu metadata"] is False
    assert buttons["Dựng lại"] is False
    assert buttons["Duyệt & dựng master"] is False
    assert buttons["Hủy job"] is False
