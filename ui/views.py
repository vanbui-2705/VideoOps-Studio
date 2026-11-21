"""Composition root for the Gradio operator interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import gradio as gr

from ui.channel_handlers import (
    list_channel_choices,
    load_channel_form,
    save_channel_form,
)
from ui.review_handlers import (
    approve_review,
    cancel_review,
    load_review,
    regenerate_review,
    retry_publish,
    save_metadata,
    skip_publish_target,
)
from ui.submission_handlers import refresh_job, submit_remix, submit_story

_CSS_PATH = Path(__file__).with_name("styles.css")
_APP_CSS = _CSS_PATH.read_text(encoding="utf-8")
_GRADIO_MAJOR_VERSION = int(gr.__version__.split(".", maxsplit=1)[0])


def _theme() -> gr.Theme:
    return gr.themes.Base(
        primary_hue=gr.themes.colors.emerald,
        secondary_hue=gr.themes.colors.teal,
        neutral_hue=gr.themes.colors.slate,
        spacing_size=gr.themes.sizes.spacing_md,
        radius_size=gr.themes.sizes.radius_sm,
    )


def _blocks_style_options() -> dict[str, Any]:
    if _GRADIO_MAJOR_VERSION >= 6:
        return {}
    return {"theme": _theme(), "css": _APP_CSS}


def _section_intro(title: str, description: str) -> None:
    gr.HTML(f'<div class="section-intro"><h2>{title}</h2><p>{description}</p></div>')


def _metadata_fields(prefix: str):
    title = gr.Textbox(label=f"{prefix} · Tiêu đề")
    description = gr.Textbox(label="Mô tả", lines=3)
    tags = gr.Textbox(label="Tags", placeholder="AI, công nghệ")
    privacy = gr.Dropdown(
        choices=["private", "unlisted", "public"],
        value="private",
        label="Privacy",
    )
    return title, description, tags, privacy


def _job_monitor(service, initial_job_id):
    with gr.Row():
        job_id = gr.Textbox(label="Job ID", value=initial_job_id)
        refresh = gr.Button("Làm mới trạng thái", interactive=service is not None)
    status = gr.Textbox(label="Trạng thái job", interactive=False)
    refresh.click(
        lambda value: refresh_job(service, value), inputs=[job_id], outputs=[status]
    )
    return job_id, status


def _build_story_workspace(service, active_channel) -> None:
    _section_intro(
        "Tạo video từ nội dung",
        "Gửi script hoặc chủ đề vào durable workflow; render tiếp tục ở worker nền.",
    )
    request_id = gr.State(value=str(uuid4()))
    with gr.Row(equal_height=False):
        with gr.Column(scale=7, elem_classes="workspace-panel"):
            source = gr.Radio(
                choices=["Script hoàn chỉnh", "Chủ đề / Prompt"],
                value="Script hoàn chỉnh",
                label="Nguồn nội dung",
            )
            content = gr.Textbox(label="Nội dung", lines=12, max_lines=20)
            title, description, tags, privacy = _metadata_fields("Story")
        with gr.Column(scale=3, elem_classes="workspace-panel"):
            gr.Markdown("### Render preset")
            gr.Textbox(value="Theo Channel Profile", label="Tỷ lệ", interactive=False)
            gr.Textbox(value="480p", label="Preview", interactive=False)
            submit = gr.Button(
                "Tạo Preview",
                variant="primary",
                interactive=service is not None,
            )
            created_job, status = _job_monitor(service, "")
    submit.click(
        lambda *values: submit_story(service, *values),
        inputs=[
            request_id,
            active_channel,
            source,
            content,
            title,
            description,
            tags,
            privacy,
        ],
        outputs=[status, created_job, request_id],
    )


def _build_remix_workspace(service, active_channel) -> None:
    _section_intro(
        "Biên tập từ nguồn có sẵn",
        "Khai báo nguồn và mốc cắt; worker thực hiện tải và chuẩn hóa ở nền.",
    )
    request_id = gr.State(value=str(uuid4()))
    rows = gr.Dataframe(
        value=[["", 0, 30, 1.0, "fill", False]],
        headers=["URL", "Bắt đầu", "Kết thúc", "Tốc độ", "Crop", "Mirror"],
        datatype=["str", "number", "number", "number", "str", "bool"],
        row_count=1,
        column_count=6,
        interactive=True,
        label="Danh sách clip",
    )
    copyright_confirmed = gr.Checkbox(
        label="Tôi xác nhận có quyền sử dụng các nguồn nội dung trên"
    )
    title, description, tags, privacy = _metadata_fields("Remix")
    submit = gr.Button(
        "Tạo Preview Remix", variant="primary", interactive=service is not None
    )
    created_job, status = _job_monitor(service, "")
    submit.click(
        lambda *values: submit_remix(service, *values),
        inputs=[
            request_id,
            active_channel,
            rows,
            copyright_confirmed,
            title,
            description,
            tags,
            privacy,
        ],
        outputs=[status, created_job, request_id],
    )


def _build_review_workspace(review) -> None:
    _section_intro(
        "Review Gate",
        "Kiểm tra preview, khóa metadata và theo dõi kết quả xuất bản từng nền tảng.",
    )
    revision = gr.State(value=None)
    with gr.Row():
        job_id = gr.Textbox(label="Job ID")
        load_button = gr.Button("Tải / Làm mới", interactive=review is not None)
    with gr.Row(equal_height=False):
        with gr.Column(scale=6, elem_classes="preview-panel"):
            preview = gr.Video(label="Preview 480p", interactive=False, height=430)
            status = gr.Textbox(label="Trạng thái pipeline", interactive=False)
            content_revision = gr.Textbox(label="Content revision", interactive=False)
            publish_targets = gr.Markdown("Chưa có publishing target.")
            manual_master = gr.File(
                label="Master dự phòng để đăng TikTok thủ công", interactive=False
            )
        with gr.Column(scale=4, elem_classes="workspace-panel"):
            title = gr.Textbox(label="Tiêu đề")
            description = gr.Textbox(label="Mô tả", lines=5)
            tags = gr.Textbox(label="Tags")
            category = gr.Textbox(label="Category", value="28")
            privacy = gr.Dropdown(
                choices=["private", "unlisted", "public"],
                value="private",
                label="Privacy",
            )
            targets = gr.CheckboxGroup(choices=[], label="Nền tảng đích")
            save_button = gr.Button("Lưu metadata", interactive=False)
            changes = gr.Textbox(label="Yêu cầu dựng lại")
            regenerate_button = gr.Button("Dựng lại", interactive=False)
            approve_button = gr.Button(
                "Duyệt & dựng master", variant="primary", interactive=False
            )
            cancel_reason = gr.Textbox(label="Lý do hủy")
            cancel_button = gr.Button("Hủy job", variant="stop", interactive=False)
            failed_target = gr.Dropdown(choices=[], label="Target lỗi")
            skip_reason = gr.Textbox(label="Lý do bỏ qua target")
            retry_button = gr.Button("Retry / Reconcile", interactive=False)
            skip_button = gr.Button("Bỏ qua target", interactive=False)

    load_button.click(
        lambda value: load_review(review, value),
        inputs=[job_id],
        outputs=[
            preview,
            status,
            revision,
            content_revision,
            title,
            description,
            tags,
            category,
            privacy,
            targets,
            save_button,
            regenerate_button,
            approve_button,
            cancel_button,
            publish_targets,
            failed_target,
            manual_master,
            retry_button,
            skip_button,
        ],
    )
    metadata_inputs = [
        job_id,
        revision,
        title,
        description,
        tags,
        category,
        privacy,
    ]
    save_button.click(
        lambda *values: save_metadata(review, *values),
        inputs=metadata_inputs,
        outputs=[status, revision],
    )
    regenerate_button.click(
        lambda *values: regenerate_review(review, *values),
        inputs=[job_id, revision, changes],
        outputs=[status, revision],
    )
    approve_button.click(
        lambda *values: approve_review(review, *values),
        inputs=[*metadata_inputs, targets],
        outputs=[status, revision],
    )
    cancel_button.click(
        lambda *values: cancel_review(review, *values),
        inputs=[job_id, revision, cancel_reason],
        outputs=[status, revision],
    )
    retry_button.click(
        lambda *values: retry_publish(review, *values),
        inputs=[job_id, revision],
        outputs=[status, revision],
    )
    skip_button.click(
        lambda *values: skip_publish_target(review, *values),
        inputs=[job_id, revision, failed_target, skip_reason],
        outputs=[status, revision],
    )


def _build_channel_workspace(channels, *, admin_enabled, choices) -> None:
    _section_intro(
        "Channel Profile",
        "Quản lý preset và credential reference; secret values không xuất hiện trong UI.",
    )
    revision = gr.State(value=None)
    selector = gr.Dropdown(
        choices=choices, label="Channel Profile", interactive=channels is not None
    )
    channel_id = gr.Textbox(label="Channel ID")
    name = gr.Textbox(label="Display name")
    niche = gr.Textbox(label="Niche")
    language = gr.Textbox(label="Language", value="vi-VN")
    persona = gr.Textbox(label="Persona")
    tone = gr.Textbox(label="Tone")
    prompt_template = gr.Textbox(label="Prompt template")
    aspect_ratio = gr.Dropdown(
        choices=["16:9", "9:16"], value="16:9", label="Aspect ratio"
    )
    voice = gr.Textbox(label="Voice")
    rate_percent = gr.Number(label="Rate %", value=0, precision=0)
    bgm_ref = gr.Textbox(label="BGM preset")
    ducking_db = gr.Number(label="Ducking dB", value=-12)
    title_template = gr.Textbox(label="Title template", value="{input}")
    description_template = gr.Textbox(label="Description template")
    hashtags = gr.Textbox(label="Hashtags")
    category_id = gr.Textbox(label="Category", value="28")
    privacy = gr.Dropdown(
        choices=["private", "unlisted", "public"], value="private", label="Privacy"
    )
    youtube_ref = gr.Textbox(label="YouTube secret reference")
    tiktok_ref = gr.Textbox(label="TikTok secret reference")
    enabled = gr.Checkbox(label="Enabled", value=True)
    credential_status = gr.Textbox(label="Credential status", interactive=False)
    save_status = gr.Textbox(label="Save status", interactive=False)
    save_button = gr.Button(
        "Save Channel Profile",
        variant="primary",
        interactive=channels is not None and admin_enabled,
    )
    outputs = [
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
        outputs=outputs,
    )
    save_button.click(
        lambda *values: save_channel_form(channels, *values),
        inputs=outputs[:-1],
        outputs=[save_status, revision],
    )


def create_ui(
    workflow: object | None = None,
    channels: object | None = None,
    review: object | None = None,
    *,
    channel_admin_enabled: bool = False,
) -> gr.Blocks:
    channel_choices, channel_status = list_channel_choices(channels, enabled_only=True)
    with (
        gr.Blocks(
            title="VideoOps Studio", fill_width=True, **_blocks_style_options()
        ) as demo,
        gr.Column(elem_classes="app-shell"),
    ):
        gr.HTML(
            '<header class="studio-header"><div><h1 class="studio-title">'
            'VideoOps Studio</h1><p class="studio-subtitle">'
            "Tạo, duyệt và phát hành video đa kênh.</p></div></header>"
        )
        with gr.Row(elem_classes="control-bar"):
            active_channel = gr.Dropdown(
                choices=channel_choices,
                label="Channel đang hoạt động",
                interactive=channels is not None,
            )
            profile_status = gr.Textbox(
                value=channel_status, label="Profile status", interactive=False
            )

            def refresh_channels():
                choices, status = list_channel_choices(channels, enabled_only=True)
                return gr.Dropdown(choices=choices), status

            refresh = gr.Button("Làm mới", interactive=channels is not None)
            refresh.click(refresh_channels, outputs=[active_channel, profile_status])
        with gr.Tabs():
            with gr.Tab("AI Story"):
                _build_story_workspace(workflow, active_channel)
            with gr.Tab("Video Remix"):
                _build_remix_workspace(workflow, active_channel)
            with gr.Tab("Review & Publish"):
                _build_review_workspace(review)
            with gr.Tab("Channel & Credentials"):
                _build_channel_workspace(
                    channels,
                    admin_enabled=channel_admin_enabled,
                    choices=list_channel_choices(channels)[0],
                )
    return demo


def launch_ui(demo: gr.Blocks, *, auth=None) -> None:
    options: dict[str, object] = {}
    if _GRADIO_MAJOR_VERSION >= 6:
        options = {"theme": _theme(), "css": _APP_CSS}
    if auth is not None:
        options["auth"] = auth
    demo.queue().launch(**options)
