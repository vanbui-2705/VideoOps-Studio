"""Safe Gradio callbacks for Story and Remix submissions."""

from __future__ import annotations

from uuid import uuid4

from core.domain.models import VideoMetadata


def submit_story(
    service,
    request_id,
    channel_id,
    source_label,
    content,
    title,
    description,
    tags,
    privacy,
):
    if service is None:
        return "Submission backend chưa sẵn sàng.", "", request_id
    try:
        source = "script" if source_label == "Script hoàn chỉnh" else "prompt"
        view = service.submit_story(
            request_id=request_id,
            channel_id=channel_id or "",
            source=source,
            content=content,
            metadata=_metadata(title, description, tags, privacy),
        )
        return f"Đã tạo {view.job_id} · {view.status.value}", view.job_id, str(uuid4())
    except Exception:  # noqa: BLE001 - UI receives only a safe status
        return (
            "Không thể tạo Story; kiểm tra kênh, nội dung và tiêu đề.",
            "",
            request_id,
        )


def submit_remix(
    service,
    request_id,
    channel_id,
    rows,
    copyright_confirmed,
    title,
    description,
    tags,
    privacy,
):
    if service is None:
        return "Submission backend chưa sẵn sàng.", "", request_id
    try:
        values = rows.values.tolist() if hasattr(rows, "values") else rows
        view = service.submit_remix(
            request_id=request_id,
            channel_id=channel_id or "",
            rows=tuple(tuple(row) for row in (values or ())),
            copyright_confirmed=bool(copyright_confirmed),
            metadata=_metadata(title, description, tags, privacy),
        )
        return f"Đã tạo {view.job_id} · {view.status.value}", view.job_id, str(uuid4())
    except Exception:  # noqa: BLE001 - UI receives only a safe status
        return (
            "Không thể tạo Remix; kiểm tra clip và xác nhận bản quyền.",
            "",
            request_id,
        )


def refresh_job(service, job_id):
    if service is None or not str(job_id).strip():
        return "Nhập Job ID để theo dõi."
    try:
        view = service.get(str(job_id))
        failure = f" · {view.failure.code}" if view.failure else ""
        return f"{view.status.value} · {view.phase.value} · {view.progress}%{failure}"
    except Exception:  # noqa: BLE001 - UI receives only a safe status
        return "Không thể tải trạng thái job."


def _metadata(title, description, tags, privacy):
    return VideoMetadata(
        title=str(title).strip(),
        description=str(description).strip(),
        tags=tuple(item.strip() for item in str(tags).split(",") if item.strip()),
        privacy=str(privacy),
    )
