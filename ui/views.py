"""Composition root for the Gradio presentation module."""

from __future__ import annotations

from pathlib import Path

import gradio as gr

from ui.channel_handlers import (
    list_channel_choices,
    load_channel_form,
    save_channel_form,
)

_CSS_PATH = Path(__file__).with_name("styles.css")
_APP_CSS = _CSS_PATH.read_text(encoding="utf-8")
_GRADIO_MAJOR_VERSION = int(gr.__version__.split(".", maxsplit=1)[0])


def _theme() -> gr.Theme:
    """Return the restrained operator-console theme used by the application."""
    return gr.themes.Base(
        primary_hue=gr.themes.colors.emerald,
        secondary_hue=gr.themes.colors.teal,
        neutral_hue=gr.themes.colors.slate,
        spacing_size=gr.themes.sizes.spacing_md,
        radius_size=gr.themes.sizes.radius_sm,
    )


def _blocks_style_options() -> dict[str, object]:
    """Keep the shell compatible with Gradio 4/5 and warning-free on Gradio 6."""
    if _GRADIO_MAJOR_VERSION >= 6:
        return {}
    return {"theme": _theme(), "css": _APP_CSS}


def _section_intro(title: str, description: str) -> None:
    gr.HTML(
        f"""
        <div class="section-intro">
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        """
    )


def _build_story_workspace() -> None:
    _section_intro(
        "Tạo video từ nội dung",
        "Chuẩn bị script hoặc chủ đề. Pipeline sẽ tạo voice, subtitle, stock và preview.",
    )
    with gr.Row(equal_height=False):
        with gr.Column(scale=7, elem_classes="workspace-panel"):
            gr.Radio(
                choices=["Script hoàn chỉnh", "Chủ đề / Prompt"],
                value="Script hoàn chỉnh",
                label="Nguồn nội dung",
            )
            gr.Textbox(
                label="Script hoặc chủ đề",
                placeholder="Dán script hoặc mô tả chủ đề cần sản xuất...",
                lines=12,
                max_lines=20,
            )
            with gr.Row():
                gr.Textbox(label="Từ khóa hình ảnh", placeholder="AI, chip, datacenter")
                gr.Dropdown(
                    choices=["Theo Channel Profile"],
                    value="Theo Channel Profile",
                    label="Giọng đọc",
                )
        with gr.Column(scale=3, elem_classes="workspace-panel"):
            gr.Markdown("### Render preset")
            gr.Textbox(label="Tỷ lệ", value="Theo Channel Profile", interactive=False)
            gr.Textbox(label="Preview", value="480p · ultrafast", interactive=False)
            gr.Textbox(label="Master", value="1080p · sau khi duyệt", interactive=False)
            gr.Button(
                "Tạo Preview",
                variant="primary",
                interactive=False,
                elem_classes="primary-action",
            )
            gr.Markdown("*Đang chờ kết nối `VideoWorkflow`.*")


def _build_remix_workspace() -> None:
    _section_intro(
        "Biên tập từ nguồn có sẵn",
        "Khai báo URL và thông số clip. Worker sẽ tải, chuẩn hóa và dựng preview trên cloud.",
    )
    with gr.Column(elem_classes="workspace-panel"):
        gr.Dataframe(
            value=[["", 0, 30, 1.0]],
            headers=["URL nguồn", "Bắt đầu (giây)", "Kết thúc (giây)", "Tốc độ"],
            datatype=["str", "number", "number", "number"],
            row_count=1,
            column_count=4,
            interactive=True,
            wrap=True,
            label="Danh sách clip",
        )
        with gr.Row():
            gr.Dropdown(
                choices=["Theo Channel Profile", "16:9", "9:16"],
                value="Theo Channel Profile",
                label="Tỷ lệ đầu ra",
            )
            gr.Dropdown(
                choices=["Fit + nền", "Crop giữa", "Crop tùy chỉnh"],
                value="Fit + nền",
                label="Xử lý khung hình",
            )
            gr.Checkbox(label="Giữ âm thanh nguồn", value=True)
        gr.Checkbox(
            label="Tôi xác nhận có quyền sử dụng các nguồn nội dung trên",
            value=False,
        )
        gr.Button(
            "Tạo Preview Remix",
            variant="primary",
            interactive=False,
            elem_classes="primary-action",
        )


def _build_review_workspace() -> None:
    _section_intro(
        "Review Gate",
        "Kiểm tra hình, tiếng, subtitle và khóa metadata trước khi dựng master.",
    )
    gr.HTML(
        """
        <div class="status-strip">
          <div class="status-cell"><span class="status-label">Job</span><span class="status-value mono-copy">—</span></div>
          <div class="status-cell"><span class="status-label">Phase</span><span class="status-value pending">Chưa có job</span></div>
          <div class="status-cell"><span class="status-label">Revision</span><span class="status-value mono-copy">—</span></div>
          <div class="status-cell"><span class="status-label">Targets</span><span class="status-value">Chưa chọn</span></div>
        </div>
        """
    )
    with gr.Row(equal_height=False):
        with gr.Column(scale=6, elem_classes="preview-panel"):
            gr.Video(label="Preview 480p", interactive=False, height=430)
            gr.Textbox(
                label="Trạng thái pipeline",
                value="Chưa có job đang review.",
                interactive=False,
            )
        with gr.Column(scale=4, elem_classes="workspace-panel"):
            gr.Textbox(label="Tiêu đề", placeholder="Tiêu đề video")
            gr.Textbox(label="Mô tả", lines=5, placeholder="Mô tả video")
            gr.Textbox(label="Tags", placeholder="tag-1, tag-2, tag-3")
            with gr.Row():
                gr.Textbox(label="Category", value="28")
                gr.Dropdown(
                    choices=["private", "unlisted", "public"],
                    value="private",
                    label="Privacy",
                )
            gr.CheckboxGroup(
                choices=["YouTube", "TikTok"],
                label="Nền tảng đích",
            )
            with gr.Row():
                gr.Button("Dựng lại", interactive=False)
                gr.Button("Hủy job", variant="stop", interactive=False)
            gr.Button(
                "Duyệt & Đăng",
                variant="primary",
                interactive=False,
                elem_classes="primary-action",
            )


def _build_channel_workspace(
    channels: object | None,
    *,
    admin_enabled: bool,
    choices: list[tuple[str, str]],
) -> None:
    _section_intro(
        "Channel Profile",
        "Manage safe production presets and credential references. Secret values remain in the deployment environment.",
    )
    revision = gr.State(value=None)
    selector = gr.Dropdown(
        choices=choices,
        label="Channel Profile",
        interactive=channels is not None,
    )
    with gr.Row(equal_height=False):
        with gr.Column(scale=6, elem_classes="workspace-panel"):
            with gr.Row():
                channel_id = gr.Textbox(label="Channel ID", placeholder="tech_vn")
                name = gr.Textbox(label="Display name", placeholder="Tech Việt Nam")
            with gr.Row():
                niche = gr.Textbox(label="Niche", placeholder="technology")
                language = gr.Textbox(label="Language", value="vi-VN")
                enabled = gr.Checkbox(label="Enabled", value=True)
            persona = gr.Textbox(label="Persona", lines=3)
            tone = gr.Textbox(label="Tone", placeholder="informative")
            prompt_template = gr.Textbox(
                label="Prompt template", lines=4, placeholder="Write about {input}"
            )
            with gr.Row():
                aspect_ratio = gr.Dropdown(
                    choices=["16:9", "9:16"], value="16:9", label="Aspect ratio"
                )
                voice = gr.Textbox(label="Voice", placeholder="vi-VN-NamMinhNeural")
                rate_percent = gr.Number(label="Rate %", value=0, precision=0)
            with gr.Row():
                bgm_ref = gr.Textbox(label="BGM preset", placeholder="tech-calm")
                ducking_db = gr.Number(label="Ducking dB", value=-12)
            title_template = gr.Textbox(label="Title template", value="{input}")
            description_template = gr.Textbox(label="Description template", lines=3)
            hashtags = gr.Textbox(label="Hashtags", placeholder="AI, Tech")
            with gr.Row():
                category_id = gr.Textbox(label="Category", value="28")
                privacy = gr.Dropdown(
                    choices=["private", "unlisted", "public"],
                    value="private",
                    label="Privacy",
                )
        with gr.Column(scale=4, elem_classes="workspace-panel danger-zone"):
            gr.Markdown("### Credential references")
            youtube_ref = gr.Textbox(
                label="YouTube secret reference", placeholder="YT_TECH"
            )
            tiktok_ref = gr.Textbox(
                label="TikTok secret reference", placeholder="TT_TECH"
            )
            credential_status = gr.Textbox(
                label="Credential status",
                value="Select a Channel Profile",
                interactive=False,
            )
            gr.Markdown(
                "Provider values are configured in the deployment secret manager and are never displayed or written here."
            )
            save_status = gr.Textbox(
                label="Save status",
                value=(
                    "Editing enabled for trusted deployment"
                    if admin_enabled
                    else "Read-only: CHANNEL_ADMIN_ENABLED=false"
                ),
                interactive=False,
            )
            save_button = gr.Button(
                "Save Channel Profile",
                variant="primary",
                interactive=channels is not None and admin_enabled,
            )

    form_outputs = [
        channel_id,
        name,
        niche,
        language,
        persona,
        tone,
        prompt_template,
        aspect_ratio,
        voice,
        rate_percent,
        bgm_ref,
        ducking_db,
        title_template,
        description_template,
        hashtags,
        category_id,
        privacy,
        youtube_ref,
        tiktok_ref,
        enabled,
        revision,
        credential_status,
    ]
    selector.change(
        lambda selected: load_channel_form(channels, selected),
        inputs=[selector],
        outputs=form_outputs,
    )
    save_button.click(
        lambda *values: save_channel_form(channels, *values),
        inputs=form_outputs[:-1],
        outputs=[save_status, revision],
    )


def create_ui(
    workflow: object | None = None,
    channels: object | None = None,
    *,
    channel_admin_enabled: bool = False,
) -> gr.Blocks:
    """Build an import-safe UI shell around injected application interfaces."""
    backend_ready = workflow is not None and channels is not None
    channels_ready = channels is not None
    channel_choices, channel_status = list_channel_choices(channels, enabled_only=True)

    def refresh_channel_components():
        refreshed_choices, refreshed_status = list_channel_choices(
            channels, enabled_only=True
        )
        return gr.Dropdown(choices=refreshed_choices), refreshed_status

    with gr.Blocks(
        title="VideoOps Studio",
        fill_width=True,
        **_blocks_style_options(),
    ) as demo:
        gr.State(value=None)
        gr.State(value=None)
        gr.State(value=None)

        with gr.Column(elem_classes="app-shell"):
            gr.HTML(
                f"""
                <header class="studio-header">
                  <div>
                    <div class="studio-eyebrow">Cloud production workspace</div>
                    <h1 class="studio-title">VideoOps Studio</h1>
                    <p class="studio-subtitle">Tạo, duyệt và phát hành video đa kênh trong một luồng kiểm soát.</p>
                  </div>
                  <div class="runtime-badge">{"Backend connected" if backend_ready else "UI preview mode"}</div>
                </header>
                """
            )

            with gr.Row(elem_classes="control-bar"):
                active_channel = gr.Dropdown(
                    choices=channel_choices,
                    label="Channel đang hoạt động",
                    info="Preset nội dung, render và tài khoản đăng",
                    scale=5,
                    interactive=channels_ready,
                )
                profile_status = gr.Textbox(
                    value=channel_status,
                    label="Profile status",
                    scale=3,
                    interactive=False,
                )
                refresh_channels = gr.Button(
                    "Làm mới", scale=1, interactive=channels_ready
                )
                refresh_channels.click(
                    refresh_channel_components,
                    outputs=[active_channel, profile_status],
                )

            with gr.Tabs():
                with gr.Tab("AI Story"):
                    _build_story_workspace()
                with gr.Tab("Video Remix"):
                    _build_remix_workspace()
                with gr.Tab("Review & Publish"):
                    _build_review_workspace()
                with gr.Tab("Channel & Credentials"):
                    _build_channel_workspace(
                        channels,
                        admin_enabled=channel_admin_enabled,
                        choices=list_channel_choices(channels)[0],
                    )

            gr.HTML(
                """
                <footer class="studio-subtitle">
                  V0 layout · backend actions remain locked until VideoWorkflow and ChannelCatalog are connected.
                </footer>
                """
            )

    return demo


def launch_ui(demo: gr.Blocks) -> None:
    """Launch the queued UI with version-appropriate style configuration."""
    launch_options: dict[str, object] = {}
    if _GRADIO_MAJOR_VERSION >= 6:
        launch_options = {"theme": _theme(), "css": _APP_CSS}
    demo.queue().launch(**launch_options)
