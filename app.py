"""Gradio entry point for NewVideo_Push."""

from ui.views import create_ui, launch_ui

__all__ = ["create_ui"]


if __name__ == "__main__":
    launch_ui(create_ui())
