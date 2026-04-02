# DEV-SPEC.md — SMART Disk Health Monitor

Generated from: `.planning/ARCH.md`, `.planning/PROJECT.md`
Date: 2026-04-01

---

## 1. Code Standards

### Language and Runtime

Python 3.11+. No other languages in scope for v1.

- **Formatter:** `black` — line length 120. Enforced on every save/commit.
- **Linter:** `ruff` — default rule set plus `flake8-bugbear`. Run on every commit.
- **Type annotations:** Required on all public functions and methods. Private helpers may omit when type is obvious from assignment. Return types always annotated on public functions.
- **Docstrings:** Google style on public functions only. Private helpers: omit unless the logic is non-obvious.

### Project Structure

```
smart-disk-monitor/
  agent/          # collection agent: enumerator, flag_detector, collector, db_writer, scheduler
  web/            # web server: app.py, templates/
  shared/         # types shared between agent and web (DeviceReading, etc.)
  tests/
  .env.example
  requirements.txt
```

Flat layout within each component directory at prototype scale. If any component directory exceeds 5 modules, split by sub-feature.

### Naming

- Variables and functions: `snake_case`, named for what they represent (`device_path`, not `dp` or `path`).
- Booleans: predicate form — `is_healthy`, `has_error`, `can_write`.
- Side-effect functions: verb phrase — `write_reading`, `probe_device`, `start_collection_cycle`.
- Pure functions: noun/question form — `detected_flags()`, `latest_readings()`.
- Constants: `UPPER_SNAKE_CASE`.
- No abbreviations beyond universally accepted domain terms (`id`, `db`, `pg`, `sql`).

### Secrets

- No credentials, passwords, connection strings, or tokens in source code — ever.
- All configuration via environment variables. Use `python-dotenv` to load `.env` locally.
- `.env.example` at project root with every required variable, a placeholder value, and a one-line comment.
- `.env` is in `.gitignore`. Never commit it.

### Input Validation

Validate all external input at system boundaries: smartctl subprocess output, PostgreSQL query results surfaced to the web layer, and any future HTTP input. Do not pass raw external strings into internal functions without validation.

---

## 2. Commit Protocol

Conventional Commits. All commits to `main` must conform.

### Format

```
<type>(<scope>): <subject>
```

**Types in use:**

| Type | When |
|---|---|
| `feat` | New user-visible capability |
| `fix` | Bug correction |
| `refactor` | Code change with no behaviour change |
| `test` | Tests only |
| `chore` | Dependencies, config, CI |
| `docs` | Documentation only |

**Scopes:** `agent`, `web`, `shared`, `db`, `infra`

**Subject line:** imperative mood, lowercase after colon, ≤72 characters, no trailing period.

**Body:** when present, explains *why* — not what (the diff shows what). Blank line between subject and body.

### One Logical Change Per Commit

Each commit is one coherent, reversible unit. If reverting the commit would undo more than one thing, split it.

### Enforcement

`pre-commit` hooks run `black --check`, `ruff`, and `commitlint` on every commit. No `--no-verify` bypasses. If a hook fails, fix the issue — don't disable the hook.

### Merge Strategy

Squash on merge to `main`. Individual commit history on feature branches is informal and need not be clean.

---

## 3. Review Criteria

Solo project — self-review applies. Before merging any branch to `main`, verify:

### Critical — blocks merge

- No hardcoded credentials, secrets, or connection strings anywhere in the diff.
- No data corruption risk: append-only insert logic is intact; no accidental `UPDATE` or `DELETE` introduced.
- No unhandled exception path that would crash the agent or web server process entirely.
- All tests in the PR pass.

### Important — requires response (fix or documented justification)

- Any new `smartctl` subprocess invocation missing a timeout.
- Any new external call (DB write, subprocess) missing error handling.
- New code path with no test coverage.
- New dependency added to `requirements.txt` without a comment explaining purpose and confirming active maintenance.

### Suggestion — advisory, no response required

- Naming clarity.
- Readability restructuring with no behaviour change.
- Performance improvement with no urgency.

### Positive note

Every self-review ends with one genuine observation of what works well. This keeps the practice honest.

---

## 4. Debt Management Policy

### What Qualifies

- **Intentional:** deliberate trade-off with a defined trigger for resolution.
- **Unintentional:** gap found after the fact — must be logged immediately on discovery.
- **Bit rot:** correct code made incorrect by a dependency or environment change.

### Recording Debt

`DEBT.md` at project root. Entry format:

```markdown
## DEBT-NNN: <short title>

**What:** <one sentence describing the gap>
**Why deferred:** <one sentence>
**Impact:** <what breaks or degrades if never resolved>
**Category:** intentional | unintentional | bit-rot
**Target resolution:** <milestone, date, or trigger condition>
**Opened:** YYYY-MM-DD
**Resolved:** —
```

### Triage

Review `DEBT.md` at the start of each milestone phase. For each open item:
1. Has the trigger condition been met? → schedule resolution.
2. Has impact grown? → re-prioritise.
3. Is the item still relevant? → close with reason if not.

### Never Acceptable as Debt

The following block shipping regardless of timeline:

- Known security vulnerabilities (CVEs, exposed credentials, broken input validation).
- Known data corruption risks (missing transaction scope on multi-row writes if introduced, race conditions that corrupt records).

These are defects, not debt.
