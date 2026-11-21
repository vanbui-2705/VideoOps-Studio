"""Revision-scoped job workspace with containment and atomic promotion."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from core.domain.errors import DomainValidationError, UnsafeWorkspacePath
from core.domain.media_models import validate_relative_path

_SAFE_JOB = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class JobWorkspace:
    def __init__(self, temp_root: Path, job_id: str, content_revision: int) -> None:
        if content_revision < 1:
            raise DomainValidationError("Workspace revision is invalid")
        safe_job = (
            job_id
            if _SAFE_JOB.fullmatch(job_id)
            else hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:32]
        )
        jobs_root = Path(temp_root) / "jobs"
        jobs_root.mkdir(parents=True, exist_ok=True)
        resolved_jobs_root = jobs_root.resolve()
        self.root = jobs_root / safe_job / f"revision-{content_revision}"
        resolved_candidate = self.root.resolve(strict=False)
        if not resolved_candidate.is_relative_to(resolved_jobs_root):
            raise UnsafeWorkspacePath("Workspace path is unsafe")
        self.root.mkdir(parents=True, exist_ok=True)
        self._resolved_root = self.root.resolve()

    def final_path(self, relative_path: str) -> Path:
        return self._contained(relative_path)

    def part_path(self, relative_path: str) -> Path:
        final = self._contained(relative_path)
        partial = final.with_name(final.name + ".part")
        partial.parent.mkdir(parents=True, exist_ok=True)
        return partial

    def promote(self, relative_path: str) -> Path:
        final = self._contained(relative_path)
        partial = final.with_name(final.name + ".part")
        if not partial.is_file():
            raise FileNotFoundError(partial.name)
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(partial, final)
        return final

    def remove_partial(self, relative_path: str) -> None:
        partial = self.part_path(relative_path)
        if partial.exists() and partial.is_file():
            partial.unlink()

    def _contained(self, relative_path: str) -> Path:
        try:
            normalized = validate_relative_path(relative_path)
        except DomainValidationError as exc:
            raise UnsafeWorkspacePath("Workspace path is unsafe") from exc
        candidate = self.root.joinpath(*normalized.split("/"))
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._resolved_root):
            raise UnsafeWorkspacePath("Workspace path is unsafe")
        return candidate
