"""Run the serialized preview and master media worker."""

from config import load_config
from core.composition import build_preview_worker


def main() -> None:
    runtime = build_preview_worker(load_config())
    try:
        runtime.worker.run_forever()
    except KeyboardInterrupt:
        runtime.worker.stop()
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
