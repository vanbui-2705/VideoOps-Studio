"""Process entry point for the Module 7 remix ingestion worker."""

from __future__ import annotations

from config import load_config
from core.composition import build_remix_worker


def main() -> None:
    runtime = build_remix_worker(load_config())
    try:
        runtime.worker.run_forever()
    except KeyboardInterrupt:
        runtime.worker.stop()
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
