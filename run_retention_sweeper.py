"""Schedule normal cancellation for expired drafts and known publish failures."""

from config import load_config
from core.composition import build_retention_sweeper
from core.runtime.observability import configure_logging


def main() -> None:
    configure_logging()
    runtime = build_retention_sweeper(load_config())
    try:
        runtime.run_forever()
    except KeyboardInterrupt:
        runtime.stop()
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
