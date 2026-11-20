"""Pure Review Gate callback helpers."""

from __future__ import annotations

import gradio as gr

from core.domain.models import JobStatus, Platform, VideoMetadata

_LABELS = {Platform.YOUTUBE: "YouTube", Platform.TIKTOK: "TikTok"}
_PLATFORMS = {label: platform for platform, label in _LABELS.items()}


def load_review(review: object | None, job_id: str):
    if review is None or not job_id.strip():
        return _empty("Nhập Job ID để tải review.")
    try:
        view = review.get(job_id.strip())
        enabled = view.status is JobStatus.AWAITING_REVIEW
        metadata = view.metadata
        choices = [_LABELS[item] for item in view.available_targets]
        return (
            view.preview_path,
            f"{view.status.value} · {view.progress}%",
            view.revision,
            str(view.content_revision),
            metadata.title,
            metadata.description,
            ", ".join(metadata.tags),
            metadata.category_id,
            metadata.privacy,
            gr.CheckboxGroup(choices=choices, value=[]),
            gr.Button(interactive=enabled),
            gr.Button(interactive=enabled),
            gr.Button(interactive=enabled),
        )
    except Exception:  # noqa: BLE001 - return a safe UI status
        return _empty("Không thể tải review hiện tại.")


def save_metadata(
    review, job_id, revision, title, description, tags, category, privacy
):
    if review is None or revision is None:
        return "Review backend chưa sẵn sàng.", revision
    try:
        view = review.update_metadata(
            job_id.strip(),
            int(revision),
            _metadata(title, description, tags, category, privacy),
        )
        return "Đã lưu metadata.", view.revision
    except Exception:  # noqa: BLE001 - return a safe UI status
        return "Không thể lưu; hãy làm mới revision.", revision


def regenerate_review(review, job_id, revision, changes):
    if review is None or revision is None:
        return "Review backend chưa sẵn sàng.", revision
    try:
        view = review.regenerate(job_id.strip(), int(revision), changes)
        return "Đã xếp hàng dựng lại preview.", view.revision
    except Exception:  # noqa: BLE001 - return a safe UI status
        return "Không thể dựng lại; kiểm tra yêu cầu.", revision


def approve_review(
    review, job_id, revision, title, description, tags, category, privacy, target_labels
):
    if review is None or revision is None:
        return "Review backend chưa sẵn sàng.", revision
    try:
        targets = tuple(_PLATFORMS[label] for label in (target_labels or []))
        view = review.approve(
            job_id.strip(),
            int(revision),
            _metadata(title, description, tags, category, privacy),
            targets,
        )
        return "Đã duyệt; master đang được dựng.", view.revision
    except Exception:  # noqa: BLE001 - return a safe UI status
        return "Không thể duyệt; kiểm tra metadata, target và revision.", revision


def _metadata(title, description, tags, category, privacy) -> VideoMetadata:
    return VideoMetadata(
        title=title.strip(),
        description=description.strip(),
        tags=tuple(value.strip() for value in tags.split(",") if value.strip()),
        category_id=category.strip(),
        privacy=privacy,
    )


def _empty(message: str):
    return (
        None,
        message,
        None,
        "—",
        "",
        "",
        "",
        "28",
        "private",
        gr.CheckboxGroup(choices=[], value=[]),
        gr.Button(interactive=False),
        gr.Button(interactive=False),
        gr.Button(interactive=False),
    )
