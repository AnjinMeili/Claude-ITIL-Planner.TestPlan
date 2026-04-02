import logging
import os
import socket
import sys

from dotenv import load_dotenv

from agent.db_writer import connect_with_backoff
from agent.scheduler import run_scheduler

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL environment variable is not set")
        sys.exit(1)

    polling_interval = int(os.environ.get("AGENT_POLLING_INTERVAL_SECONDS", "300"))
    device_timeout = int(os.environ.get("AGENT_DEVICE_TIMEOUT_SECONDS", "30"))
    host_id = socket.gethostname()

    logger.info("agent starting | host_id=%s", host_id)

    conn = connect_with_backoff(database_url)

    run_scheduler(
        host_id=host_id,
        conn=conn,
        polling_interval_seconds=polling_interval,
        device_timeout_seconds=device_timeout,
    )


if __name__ == "__main__":
    main()
