from core.models import JobStatus
from core.state_manager import StateManager


def test_state_manager_lifecycle(tmp_path):
    mgr = StateManager(storage_dir=str(tmp_path))
    job = mgr.create_job(channel_id="tech_vn", aspect_ratio="16:9")
    assert job.status == JobStatus.IDLE
    assert job.channel_id == "tech_vn"

    mgr.update_job_status(job.job_id, JobStatus.RENDERING_PREVIEW)
    assert mgr.get_job(job.job_id).status == JobStatus.RENDERING_PREVIEW


def test_zero_retention_purge(tmp_path):
    mgr = StateManager(storage_dir=str(tmp_path))
    job = mgr.create_job(channel_id="test_purge")

    chunk1 = tmp_path / "chunk1.mp4"
    chunk1.write_text("chunk 1 raw bytes")
    audio = tmp_path / "audio.wav"
    audio.write_text("audio wave bytes")
    master = tmp_path / "master.mp4"
    master.write_text("final master bytes")

    mgr.register_temp_file(job.job_id, chunk1)
    mgr.register_temp_file(job.job_id, audio)
    job.master_path = str(master)

    assert chunk1.exists()
    assert audio.exists()
    assert master.exists()

    deleted = mgr.purge_job_artifacts(job.job_id)
    assert deleted == 3
    assert not chunk1.exists()
    assert not audio.exists()
    assert not master.exists()
    assert len(job.temp_files) == 0
    assert job.master_path is None
