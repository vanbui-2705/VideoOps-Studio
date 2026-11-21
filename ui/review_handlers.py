"""Pure Review Gate callback helpers."""

from __future__ import annotations

from typing import Any

import gradio as gr

from core.domain.models import JobStatus, Platform, VideoMetadata

_LABELS = {Platform.YOUTUBE: "YouTube", Platform.TIKTOK: "TikTok"}
_PLATFORMS = {label: platform for platform, label in _LABELS.items()}


def load_review(review: Any | None, job_id: str):
    if review is None or not job_id.strip():
        return _empty("Nhập Job ID để tải review.")
    try:
        view = review.get(job_id.strip())
        enabled = view.status is JobStatus.AWAITING_REVIEW
        metadata = view.metadata
        choices = [_LABELS[item] for item in view.available_targets]
        failed_targets = [
            _LABELS[item.platform]
            for item in view.publish_targets
            if item.status.value in {"FAILED", "UNKNOWN"}
        ]
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
            gr.Button(interactive="cancel" in view.allowed_actions),
            _target_summary(view),
            gr.Dropdown(
                choices=failed_targets,
                value=failed_targets[0] if failed_targets else None,
            ),
            view.manual_master_path,
            gr.Button(interactive="retry" in view.allowed_actions),
            gr.Button(
                interactive="skip_target" in view.allowed_actions
                and bool(failed_targets)
            ),
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


def retry_publish(review, job_id, revision):
    if review is None or revision is None:
        return "Publish backend chưa sẵn sàng.", revision
    try:
        view = review.retry_publish(job_id.strip(), int(revision))
        return "Đã xếp hàng retry/reconcile.", view.revision
    except Exception:  # noqa: BLE001 - safe operator message
        return "Không thể retry; hãy làm mới revision.", revision


def cancel_review(review, job_id, revision, reason):
    if review is None or revision is None:
        return "Review backend chưa sẵn sàng.", revision
    try:
        view = review.cancel(job_id.strip(), int(revision), reason)
        return "Đã xếp hàng dọn dữ liệu.", view.revision
    except Exception:  # noqa: BLE001 - safe operator message
        return "Không thể hủy; nhập lý do và làm mới revision.", revision


def skip_publish_target(review, job_id, revision, target_label, reason):
    if review is None or revision is None or target_label not in _PLATFORMS:
        return "Chọn một target lỗi.", revision
    try:
        view = review.skip_target(
            job_id.strip(), int(revision), _PLATFORMS[target_label], reason
        )
        return "Đã bỏ qua target kèm lý do.", view.revision
    except Exception:  # noqa: BLE001 - safe operator message
        return "Không thể bỏ qua; nhập lý do và làm mới revision.", revision


def _target_summary(view) -> str:
    if not view.publish_targets:
        return "Chưa có publishing target."
    rows = ["| Platform | Status | Public URL | Error |", "|---|---|---|---|"]
    for target in view.publish_targets:
        rows.append(
            f"| {_LABELS[target.platform]} | {target.status.value} | "
            f"{target.public_url or '—'} | {target.last_error_code or '—'} |"
        )
    return "\n".join(rows)


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
        gr.Button(interactive=False),
        "Chưa có publishing target.",
        gr.Dropdown(choices=[], value=None),
        None,
        gr.Button(interactive=False),
        gr.Button(interactive=False),
    )
