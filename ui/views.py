"""Composition root for the Gradio presentation module."""

from __future__ import annotations

from pathlib import Path

import gradio as gr

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


def _build_channel_workspace() -> None:
    _section_intro(
        "Channel Profile",
        "Quản lý preset nội dung và credential reference. Secret không được đọc ngược ra giao diện.",
    )
    gr.HTML(
        '<div class="credential-note">Khu vực credential phải được bảo vệ bằng authentication trước khi deployment public.</div>'
    )
    with gr.Row(equal_height=False):
        with gr.Column(scale=6, elem_classes="workspace-panel"):
            with gr.Row():
                gr.Textbox(label="Channel ID", placeholder="tech_vn")
                gr.Textbox(label="Tên hiển thị", placeholder="Tech Việt Nam")
            gr.Textbox(
                label="Persona",
                lines=4,
                placeholder="Chủ đề, tone và đối tượng người xem",
            )
            gr.Textbox(
                label="Prompt template", lines=6, placeholder="Template dùng {input}..."
            )
            with gr.Row():
                gr.Dropdown(choices=["16:9", "9:16"], value="16:9", label="Tỷ lệ")
                gr.Textbox(label="Voice", placeholder="vi-VN-NamMinhNeural")
                gr.Textbox(label="BGM preset", placeholder="tech-calm")
        with gr.Column(scale=4, elem_classes="workspace-panel danger-zone"):
            gr.Markdown("### Credential references")
            gr.Textbox(label="YouTube secret reference", placeholder="YT_TECH")
            gr.Textbox(label="TikTok secret reference", placeholder="TT_TECH")
            gr.Textbox(
                label="Cập nhật secret",
                placeholder="Giá trị sẽ không hiển thị lại sau khi lưu",
                type="password",
            )
            gr.Button("Lưu Channel Profile", variant="primary", interactive=False)


def create_ui(
    workflow: object | None = None,
    channels: object | None = None,
) -> gr.Blocks:
    """Build an import-safe UI shell around injected application interfaces."""
    backend_ready = workflow is not None and channels is not None

    with gr.Blocks(
        title="NewVideo Studio",
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
                    <h1 class="studio-title">NewVideo Studio</h1>
                    <p class="studio-subtitle">Tạo, duyệt và phát hành video đa kênh trong một luồng kiểm soát.</p>
                  </div>
                  <div class="runtime-badge">{"Backend connected" if backend_ready else "UI preview mode"}</div>
                </header>
                """
            )

            with gr.Row(elem_classes="control-bar"):
                gr.Dropdown(
                    choices=[],
                    label="Channel đang hoạt động",
                    info="Preset nội dung, render và tài khoản đăng",
                    scale=5,
                    interactive=backend_ready,
                )
                gr.Textbox(
                    value="Chưa kết nối ChannelCatalog",
                    label="Profile status",
                    scale=3,
                    interactive=False,
                )
                gr.Button("Làm mới", scale=1, interactive=backend_ready)

            with gr.Tabs():
                with gr.Tab("AI Story"):
                    _build_story_workspace()
                with gr.Tab("Video Remix"):
                    _build_remix_workspace()
                with gr.Tab("Review & Publish"):
                    _build_review_workspace()
                with gr.Tab("Channel & Credentials"):
                    _build_channel_workspace()

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
