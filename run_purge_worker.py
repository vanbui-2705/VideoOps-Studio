"""Run the serialized verified zero-retention worker."""

from config import load_config
from core.composition import build_purge_worker
from core.runtime.observability import configure_logging


def main() -> None:
    configure_logging()
    runtime = build_purge_worker(load_config())
    try:
        runtime.worker.run_forever()
    except KeyboardInterrupt:
        runtime.worker.stop()
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
