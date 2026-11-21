from pathlib import Path

import pytest

from core.adapters.media.workspace import JobWorkspace
from core.adapters.purge.workspace import WorkspacePurger


def test_workspace_purger_removes_all_job_revisions_but_not_other_jobs(
    tmp_path: Path,
) -> None:
    first = JobWorkspace(tmp_path, "job-purge", 1)
    second = JobWorkspace(tmp_path, "job-purge", 2)
    other = JobWorkspace(tmp_path, "job-other", 1)
    first_file = first.final_path("preview/preview.mp4")
    second_file = second.final_path("master/master.mp4.part")
    other_file = other.final_path("master/master.mp4")
    for path, content in (
        (first_file, b"preview"),
        (second_file, b"partial"),
        (other_file, b"keep"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    result = WorkspacePurger(tmp_path).purge("job-purge", 2)

    assert result.remaining_bytes == 0
    assert result.deleted_files == 2
    assert not first.root.parent.exists()
    assert other_file.read_bytes() == b"keep"


def test_workspace_purger_is_idempotent(tmp_path: Path) -> None:
    workspace = JobWorkspace(tmp_path, "job-purge", 1)
    media = workspace.final_path("voice/audio.mp3")
    media.parent.mkdir(parents=True)
    media.write_bytes(b"voice")
    purger = WorkspacePurger(tmp_path)

    first = purger.purge("job-purge", 1)
    second = purger.purge("job-purge", 1)

    assert first.remaining_bytes == second.remaining_bytes == 0
    assert second.deleted_files == 0


def test_workspace_purger_unlinks_symlink_without_deleting_target(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"keep")
    workspace = JobWorkspace(tmp_path, "job-purge", 1)
    link = workspace.root / "outside-link.mp4"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable")

    result = WorkspacePurger(tmp_path).purge("job-purge", 1)

    assert result.remaining_bytes == 0
    assert outside.read_bytes() == b"keep"
