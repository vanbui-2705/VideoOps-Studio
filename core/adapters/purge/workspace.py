"""Contained, idempotent deletion of one job's complete media workspace."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from core.adapters.media.workspace import JobWorkspace
from core.application.purge import PurgeResult
from core.domain.errors import UnsafeWorkspacePath


class WorkspacePurger:
    def __init__(self, temp_root: Path, *, max_files: int = 10000) -> None:
        if max_files < 1:
            raise ValueError("Purge scan limit must be positive")
        self._temp_root = Path(temp_root)
        self._max_files = max_files

    def purge(
        self,
        job_id: str,
        content_revision: int,
        heartbeat: Callable[[], None] | None = None,
    ) -> PurgeResult:
        workspace = JobWorkspace(self._temp_root, job_id, content_revision)
        job_root = workspace.root.parent
        jobs_root = (self._temp_root / "jobs").resolve()
        if not job_root.resolve().is_relative_to(jobs_root):
            raise UnsafeWorkspacePath("Purge workspace is unsafe")
        deleted = _delete_tree(job_root, [self._max_files], heartbeat)
        return PurgeResult(deleted, _tree_bytes(job_root, [self._max_files]))


def _delete_tree(
    root: Path,
    budget: list[int],
    heartbeat: Callable[[], None] | None = None,
) -> int:
    if not root.exists() and not root.is_symlink():
        return 0
    deleted = 0
    try:
        entries = tuple(os.scandir(root))
    except OSError:
        return 0
    for entry in entries:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        path = Path(entry.path)
        try:
            is_junction = getattr(path, "is_junction", lambda: False)()
            if entry.is_dir(follow_symlinks=False) and not is_junction:
                deleted += _delete_tree(path, budget, heartbeat)
            else:
                path.unlink()
                deleted += 1
            if heartbeat:
                heartbeat()
        except OSError:
            continue
    try:
        root.rmdir()
    except OSError:
        pass
    return deleted


def _tree_bytes(root: Path, budget: list[int]) -> int:
    if not root.exists() and not root.is_symlink():
        return 0
    try:
        entries = tuple(os.scandir(root))
    except OSError:
        return 1
    total = 0
    for entry in entries:
        if budget[0] <= 0:
            return max(1, total)
        budget[0] -= 1
        path = Path(entry.path)
        try:
            is_junction = getattr(path, "is_junction", lambda: False)()
            if entry.is_dir(follow_symlinks=False) and not is_junction:
                total += _tree_bytes(path, budget)
            else:
                total += max(1, entry.stat(follow_symlinks=False).st_size)
        except OSError:
            total += 1
    return total
