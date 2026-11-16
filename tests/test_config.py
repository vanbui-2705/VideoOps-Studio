from pathlib import Path

from config import load_config


def test_load_config_defaults(tmp_path):
    cfg = load_config()
    assert cfg.MAX_FFMPEG_THREADS == 2
    assert isinstance(cfg.BASE_DIR, Path)
    assert Path(cfg.TEMP_DIR).exists()
    assert Path(cfg.OUTPUT_DIR).exists()
    assert Path(cfg.CHANNELS_DIR).exists()
