# Code Review: SMART Disk Health Monitor -- Full Project Review

**DEV-SPEC.md:** Found at `/Users/james/src/test/testplan/.planning/DEV-SPEC.md`

**Summary:** The implementation is a faithful execution of the planning artifacts. All PLAN.md phases are addressed, ADR decisions are honoured, and the ARCH.md interface contracts are followed closely. The main concerns are a thread-safety issue in the web server's request timing, a foreign key ordering dependency between the DB writer and host upsert, and a missing `LOG_LEVEL` variable in `.env.example`. Code quality is high across the board.

---

## Part 1 -- Plan Fidelity

### PLAN.md Step Coverage

| Step | Status | Notes |
|---|---|---|
| 1.1 Project scaffold | Done | Directory structure, requirements.txt, .env.example, .gitignore all present |
| 1.2 Database schema | Done | `db/schema.sql` matches ARCH.md section 3. Index on `(host_id, device_path, collected_at DESC)` included. |
| 1.3 Shared types | Done | `shared/types.py` defines all four dataclasses per ARCH.md section 4. Tests in `test_types.py`. |
| 1.4 Device Enumerator | Done | `agent/enumerator.py` with `lsblk -d -o NAME -n`. Unit and integration tests present. |
| 1.5 Flag Detector | Done | `agent/flag_detector.py` uses JSON info probe per ADR-002. Timeout, fallback, and error handling all present. |
| 1.6 SMART Collector | Done | `agent/collector.py` with FM-2 null-safety enforced. |
| 1.7 DB Writer | Done | `agent/db_writer.py` with exponential backoff, per-record failure isolation, reconnect-once logic. |
| 1.8 Scheduler + entry point | Done | `agent/scheduler.py` and `agent/__main__.py`. NFR-03 (first cycle immediate), NFR-11/12/13 logging. |
| 2.1 Web server scaffold | Done | `web/app.py`, `web/__main__.py`, `web/templates/index.html`. |
| 2.2 Query implementation | Done | `DISTINCT ON` query matches ARCH.md section 4.3 exactly. |
| 3.1 Host identity | Done | `socket.gethostname()` used in `agent/__main__.py`. Tested in `test_host_identity.py`. |
| 3.2 Remote deployment | Done | `infra/smart-agent.service`, `infra/smart-web.service`, `README.md` deployment procedure. |
| 3.3 PostgreSQL access | Done | `README.md` documents both direct TCP and SSH tunnel options per ADR-004. |
| 3.4 Multi-machine test | Done | `test_integration_phase3.py` covers AC-05-01 and AC-05-02. |
| 3.5 New disk auto-discovery | Done | `test_integration_phase3.py::test_new_device_appears_after_next_cycle` covers AC-04-01. |

### Use Case and Acceptance Criteria Coverage

| ID | Covered? | How |
|---|---|---|
| UC-01 / AC-01-01 | Yes | Web route + template renders table with required columns. `test_web.py::test_distinct_on_query_uses_correct_columns`. |
| UC-01 / AC-01-02 | Yes | Integration test `test_multiple_hosts_appear_in_single_query`. |
| UC-01 / AC-01-03 | Yes | By design -- browser-only interaction after setup. |
| UC-02 / AC-02-01, AC-02-02 | Yes | Scheduler iterates all devices, writes all successful results. |
| UC-02 / AC-02-03 | Yes | `run_scheduler` polling loop. |
| UC-03 / AC-03-01 | Partial | Handled by flag detector + collector code, but no dedicated test with both SATA and NVMe mocked in the same cycle. Covered implicitly by separate unit tests. |
| UC-03 / AC-03-02 | Yes | Flag detector maps USB type to `--device=sat`. |
| UC-03 / AC-03-03 | Yes | `test_flag_detector.py::test_no_hardcoded_device_map` verifies no file I/O. |
| UC-04 / AC-04-01, AC-04-02 | Yes | Integration test `test_new_device_appears_after_next_cycle`. |
| UC-05 / AC-05-01 | Yes | Integration test `test_multiple_hosts_appear_in_single_query`. |
| UC-05 / AC-05-02 | Yes | Integration test `test_concurrent_agent_writes_no_conflict`. |
| UC-06 / AC-06-01, AC-06-02 | Yes | Append-only INSERT (no UPDATE/DELETE in agent). Schema uses `BIGSERIAL PK`. Persistence across restarts is by design. |

### ARCH.md Failure Mode Mitigations

| FM | Status | Implementation |
|---|---|---|
| FM-1: smartctl hang | Done | `subprocess.run(timeout=...)` in both `flag_detector.py:36` and `collector.py:29`. Configurable via env var. |
| FM-2: Null health_status | Done | `_parse_health_status()` returns "UNKNOWN" as default. `health_status TEXT NOT NULL` in schema.sql. |
| FM-4: Postgres unreachable at startup | Done | `connect_with_backoff()` with exponential backoff up to `max_wait_seconds`. |
| FM-6: Stale data visibility | Done | `collected_at` column displayed in web table with UTC label. |

### ADR Compliance

| ADR | Decision | Honoured? |
|---|---|---|
| ADR-001: Python | Agent and web in Python 3 | Yes |
| ADR-002: JSON info probe | `smartctl -i -j` for flag detection | Yes |
| ADR-003: Server-side HTML | Jinja2 template, no JavaScript | Yes |
| ADR-004: Direct TCP | Agent connects via `psycopg2.connect(DATABASE_URL)` | Yes |

---

## Part 2 -- Code Quality

### Critical

**`web/app.py:35-40` -- Thread-safety issue in request timing using `app._request_start`**
The `before_request` hook stores the request start time on the `app` object (`app._request_start`). Flask's `app` is a process-global singleton. Under a threaded WSGI server (which Flask's dev server uses by default with `threaded=True`), concurrent requests will overwrite each other's start time, producing incorrect timing in the `after_request` log. Additionally, the `index()` handler resets `app._request_start` again at line 55, making the `before_request` hook partially redundant. This should use `flask.g` (the per-request context) instead of `app`. While the current deployment is low-traffic and unlikely to see concurrent requests, this is a correctness defect in the request logging contract (NFR-14) that produces wrong data silently.

**`web/app.py:39-47` -- NFR-14 request log format is incorrect**
The `after_request` log format string logs `response.status_code` twice and references `response.headers.get("X-Request-Path", "")` which is never set anywhere. The intended log format per NFR-14 is: request timestamp, HTTP method, path, response status code, response time. The current implementation logs `status_code, "", status_code, duration_ms` -- missing method and path entirely, and duplicating the status code. The request method and path are logged separately in the `index()` handler, but the `after_request` hook (which should be the single authoritative request log per NFR-14) is broken.

---

### Important

**`db/schema.sql:12-13` -- Foreign key on device_reading.host_id requires host row to exist before any device_reading insert**
The schema declares `host_id TEXT NOT NULL REFERENCES host(host_id)` on `device_reading`. In `agent/scheduler.py:68-69`, `write_readings()` is called *before* `upsert_host()`. If this is the first cycle for a new host, the INSERT into `device_reading` will fail with a foreign key violation because no row exists in `host` yet. The `upsert_host` call must happen before `write_readings`, or the FK constraint must be removed. This will cause a complete failure of the first collection cycle for every new host deployment.

**`web/app.py:72` -- Database exception details leaked to HTTP response**
The 503 response includes `{exc}` which contains the full psycopg2 error message. This may expose the database hostname, port, username, or schema details to any browser client. ARCH.md section 4.3 specifies "plain-text error body" but does not call for exception details. Since there is no authentication on the web UI (NFR-05), any network client can trigger this by accessing the page when Postgres is down. The response should omit the exception details.

**`agent/scheduler.py:48` -- Only `timeout` and `smartctl_not_found` errors skip DB write; other error values are still written**
The condition `if result.error == "timeout" or result.error == "smartctl_not_found"` checks for exactly two error strings. If `collect_device` returns any other non-None error string (e.g. `"json_parse_error (exit 1)"`), the reading is still written to the database with `health_status="UNKNOWN"`. Per ARCH.md section 4.1: "If the subprocess times out, the record is skipped (not written to DB)." This is correctly implemented for timeouts. However, the `json_parse_error` case is written to DB, which is arguably correct per FM-2 (UNKNOWN rows are still written so the operator can see the device). The behaviour is consistent with ARCH.md but the conditional is fragile -- a future error string addition could accidentally bypass this filter. Consider using a more explicit pattern.

**`.env.example` -- Missing `LOG_LEVEL` variable**
`agent/__main__.py:14` and `web/__main__.py:10` both read `LOG_LEVEL` from the environment, but `.env.example` does not list it. DEV-SPEC.md section 1 requires: "`.env.example` at project root with every required variable, a placeholder value, and a one-line comment."

---

### Suggestions

**`agent/scheduler.py:87-127` -- `run_scheduler` conn parameter has no type annotation**
The `conn` parameter on both `run_scheduler` and `run_collection_cycle` is untyped. DEV-SPEC.md requires type annotations on all public functions. Should be `conn: psycopg2.extensions.connection`.

**`web/app.py:26-30` -- `_get_connection` opens a new connection per request with no pooling**
Each HTTP request opens and closes a fresh Postgres connection. At the expected scale (few requests per day) this is fine, but if usage increases, connection pooling would be beneficial. No action required now.

**`web/app.py:51-74` -- `index()` does double request logging**
The `before_request`/`after_request` hooks and the manual logging inside `index()` both log request information. Once the `after_request` hook is fixed, the manual logging inside `index()` should be removed to avoid duplicate log entries.

**`agent/collector.py:48` -- The `result.error == "timeout"` check in scheduler relies on string matching across module boundaries**
The error strings `"timeout"`, `"smartctl_not_found"`, and `"json_parse_error"` are implicit contracts between `collector.py` and `scheduler.py`. These would be safer as constants in `shared/types.py` or as an enum.

**`db/schema.sql` -- No comment about the recommended index from ARCH.md section 4.3**
The index `idx_device_reading_lookup` is present and correct. A SQL comment noting it supports the `DISTINCT ON` web query would aid future readers.

**`requirements.txt` -- Dependencies lack inline comments explaining purpose**
DEV-SPEC.md section 3 (Important tier) requires: "New dependency added to `requirements.txt` without a comment explaining purpose and confirming active maintenance." The dependencies are all well-known packages, but short comments (e.g. `# PostgreSQL adapter`, `# Web framework`) would satisfy the standard.

---

### Positive Note

The `_parse_health_status()` function in `agent/collector.py:104-114` is an exemplary implementation of a defensive parser. It explicitly checks `True` and `False` with identity comparison (`is True`, `is False`) rather than truthiness, which correctly handles edge cases where the JSON field is present but contains a non-boolean value (0, empty string, null). The fallback to `"UNKNOWN"` is always reached for any unexpected input. Combined with the `NOT NULL` constraint in the schema, this creates a two-layer defence against FM-2 (null health_status) that is both correct and easy to verify by reading. The corresponding test `test_health_status_never_null` in `test_collector.py` exercises four different malformed inputs, providing good confidence that the guarantee holds.

The test suite overall is thorough and well-structured. The separation of unit tests (mocked subprocess) from integration tests (marked with `@pytest.mark.integration`) allows fast feedback during development while still supporting full-stack verification. The `test_no_hardcoded_device_map` test is a creative approach to verifying AC-03-03 by asserting `builtins.open` was never called.

---

## Merge Decision

**Blocked -- do not merge.** Three findings must be resolved:

1. **Critical: `web/app.py:35-47`** -- Request timing stored on app singleton is not thread-safe, and the `after_request` log format is broken (duplicated status code, missing method/path, referencing non-existent header). Fix by using `flask.g` for timing and correcting the log format string to include `request.method` and `request.path`.

2. **Critical: `web/app.py:72`** -- Exception details leaked in 503 response. Remove `{exc}` from the response body.

3. **Important (blocks first-run): `agent/scheduler.py:68-69` / `db/schema.sql:12-13`** -- Foreign key ordering: `write_readings` is called before `upsert_host`, causing FK violation on first cycle for any new host. Swap the call order (upsert host first, then write readings).

All other Important and Suggestion items are noted for the author's response.
