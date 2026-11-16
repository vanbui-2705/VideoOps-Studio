"""State management, task persistence, and zero-retention artifact lifecycle."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from core.models import JobStatus, VideoJob, VideoMetadata


class StateManager:
    """Manages video job lifecycle and guarantees artifact eviction."""

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self.storage_dir = Path(storage_dir) if storage_dir else Path("temp") / "state"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, VideoJob] = {}

    def create_job(self, channel_id: str, aspect_ratio: str = "16:9") -> VideoJob:
        """Initialize a new video production job."""
        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        job = VideoJob(
            job_id=job_id,
            channel_id=channel_id,
            aspect_ratio=aspect_ratio,
            status=JobStatus.IDLE,
            metadata=VideoMetadata(),
        )
        self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> VideoJob | None:
        """Retrieve job state by ID."""
        return self._jobs.get(job_id)

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: str | None = None,
    ) -> VideoJob:
        """Update job progress state."""
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job {job_id} not found")
        job.status = status
        job.updated_at = time.time()
        if error_message:
            job.error_message = error_message
        return job

    def register_temp_file(self, job_id: str, file_path: str | Path) -> None:
        """Track intermediate asset for guaranteed post-render cleanup."""
        job = self.get_job(job_id)
        if not job:
            return
        abs_path = str(Path(file_path).resolve())
        if abs_path not in job.temp_files:
            job.temp_files.append(abs_path)

    def purge_job_artifacts(self, job_id: str) -> int:
        """
        Zero-Retention Policy:
        Evict all temporary media chunks, intermediate audio/subtitles,
        and rendered video files associated with this job.
        Returns the number of deleted files.
        """
        job = self.get_job(job_id)
        if not job:
            return 0

        files_to_delete: list[str] = list(job.temp_files)
        if job.preview_path:
            files_to_delete.append(str(Path(job.preview_path).resolve()))
        if job.master_path:
            files_to_delete.append(str(Path(job.master_path).resolve()))

        deleted_count = 0
        for fpath in files_to_delete:
            try:
                p = Path(fpath)
                if p.is_file():
                    p.unlink(missing_ok=True)
                    deleted_count += 1
            except OSError:
                # Log or ignore transient file locking
                pass

        job.temp_files.clear()
        job.preview_path = None
        job.master_path = None
        return deleted_count

    def prune_abandoned_jobs(self, max_age_seconds: int = 21600) -> int:
        """Clean up artifacts for jobs untouched for more than max_age_seconds (default: 6h)."""
        now = time.time()
        purged = 0
        for job_id, job in list(self._jobs.items()):
            if now - job.updated_at > max_age_seconds:
                purged += self.purge_job_artifacts(job_id)
                self._jobs.pop(job_id, None)
        return purged
