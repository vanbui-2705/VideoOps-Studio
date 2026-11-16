"""Public-interface tests for the Gradio application shell."""

import gradio as gr

from app import create_ui


def test_create_ui_returns_blocks_without_dependencies() -> None:
    """The UI shell can be composed before production adapters exist."""
    demo = create_ui()

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
