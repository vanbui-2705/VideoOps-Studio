from pathlib import Path

from config import load_config


def test_load_config_defaults(tmp_path):
    cfg = load_config()
    assert cfg.MAX_FFMPEG_THREADS == 2
    assert isinstance(cfg.BASE_DIR, Path)
    assert Path(cfg.TEMP_DIR).exists()
    assert Path(cfg.OUTPUT_DIR).exists()
    assert Path(cfg.CHANNELS_DIR).exists()
    assert cfg.REMIX_MAX_SOURCES == 10
    assert cfg.REMIX_MAX_DOWNLOAD_BYTES == 1024 * 1024 * 1024


def test_database_secrets_are_loaded_but_hidden_from_repr(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://videoops:super-secret@db.example/videoops",
    )
    monkeypatch.setenv("WORK_LEASE_SECONDS", "120")
    monkeypatch.setenv("CHANNEL_ADMIN_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "VIDEOOPS_TEST_SECRET_9f37")
    monkeypatch.setenv("OPENAI_API_KEY", "OPENAI_TEST_SECRET_67d1")
    monkeypatch.setenv("PIXABAY_API_KEY", "PIXABAY_TEST_SECRET_71c2")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "configured-model")

    cfg = load_config()

    assert cfg.DATABASE_URL is not None
    assert cfg.WORK_LEASE_SECONDS == 120
    assert cfg.CHANNEL_ADMIN_ENABLED is True
    assert cfg.LLM_PROVIDER == "openai"
    assert cfg.LLM_MODEL == "configured-model"
    assert "super-secret" not in repr(cfg)
    assert "VIDEOOPS_TEST_SECRET_9f37" not in repr(cfg)
    assert "OPENAI_TEST_SECRET_67d1" not in repr(cfg)
    assert "PIXABAY_TEST_SECRET_71c2" not in repr(cfg)
