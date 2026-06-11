"""Entry point: ``python -m persistent_memory.daemon`` or uvicorn target.

Exposes a module-level ``app`` so launchd/uvicorn can load
``persistent_memory.daemon.__main__:app`` directly.
"""

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DAEMON_HOST, DAEMON_PORT
from persistent_memory.daemon.token import default_records_dir

DEFAULT_RECORDS_DIR = default_records_dir()
app = create_app(records_dir=DEFAULT_RECORDS_DIR)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=DAEMON_HOST, port=DAEMON_PORT)


if __name__ == "__main__":
    main()
