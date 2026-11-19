from pathlib import Path

import pytest

from core.adapters.media.workspace import JobWorkspace
from core.domain.errors import UnsafeWorkspacePath


def test_workspace_promotes_partial_file_atomically(tmp_path: Path) -> None:
    workspace = JobWorkspace(tmp_path, "job-1", 2)
    partial = workspace.part_path("voice/narration.mp3")
    partial.write_bytes(b"audio")

    final = workspace.promote("voice/narration.mp3")

    assert final.read_bytes() == b"audio"
    assert not partial.exists()
    assert (
        final.relative_to(tmp_path)
        .as_posix()
        .endswith("jobs/job-1/revision-2/voice/narration.mp3")
    )


def test_workspace_rejects_traversal_and_symlink_escape(tmp_path: Path) -> None:
    workspace = JobWorkspace(tmp_path, "job-1", 1)
    with pytest.raises(UnsafeWorkspacePath):
        workspace.final_path("../../outside.txt")

    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace.root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(UnsafeWorkspacePath):
        workspace.final_path("linked/escape.txt")
