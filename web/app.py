import logging
import os
import time

import psycopg2
import psycopg2.extras
from flask import Flask, Response, g, render_template, request

app = Flask(__name__)
logger = logging.getLogger(__name__)

# Query: latest reading per (host_id, device_path), ordered for stable rendering
_LATEST_READINGS_SQL = """
SELECT DISTINCT ON (host_id, device_path)
    host_id,
    device_path,
    device_type,
    health_status,
    smart_flags_used,
    collected_at
FROM device_reading
ORDER BY host_id, device_path, collected_at DESC
"""


def _get_connection() -> psycopg2.extensions.connection:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(database_url)


@app.before_request
def _start_timer() -> None:
    g.request_start = time.monotonic()


@app.after_request
def _log_request(response: Response) -> Response:
    duration_ms = int((time.monotonic() - g.get("request_start", time.monotonic())) * 1000)
    # NFR-14: timestamp, method, path, status, response_ms
    logger.info(
        "web: %s %s %d %dms",
        request.method,
        request.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.route("/")
def index() -> Response:
    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_LATEST_READINGS_SQL)
            rows = cur.fetchall()
        conn.close()
    except Exception as exc:
        logger.error("web: database error: %s", exc)
        return Response("Service unavailable: database error", status=503, mimetype="text/plain")

    return render_template("index.html", rows=rows)
