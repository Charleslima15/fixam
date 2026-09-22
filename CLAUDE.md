# FixAm

WhatsApp-based network in Buea, Cameroon connecting customers who need a service (plumbing, electrical, repairs) to vetted providers. Providers pay pre-paid lead credits (MTN MoMo) for each introduction they accept. Customers never pay.

## Docs — read on demand, not every session
- `docs/requirements.md` — technical requirements. Numbered IDs (FR-ACC-01 etc.). **Source of truth for behaviour.** Read only the sections relevant to the current task.
- `docs/product-definition.md` — product reasoning and the "why". Read only if a requirement's intent is unclear.

## Stack
Python 3.12, FastAPI, SQLAlchemy 2.0 (typed), Alembic, PostgreSQL, pytest. One web process, one worker process. **No Redis, no Celery.** Background jobs use a Postgres `job` table claimed with `FOR UPDATE SKIP LOCKED`.

## Invariants — never violate
1. Any operation touching credits is a **single DB transaction**.
2. `credit_ledger` is **append-only**, enforced in the database. Balance is derived from entries.
3. Acceptance locks the request row (`SELECT ... FOR UPDATE`); exactly one assignment and one debit per request.
4. The AI model **never receives provider names or phone numbers**, and never triggers state changes. It returns validated JSON; deterministic code acts on it.
5. Contact details are released only by code keyed on the `assigned` transition.
6. All webhook and callback handlers are **idempotent** (unique external IDs).
7. State transitions follow `docs/requirements.md` §4 exactly; invalid transitions raise.
8. Thresholds, wave sizes, timeouts, caps and prices live in the `config` table, not constants.
9. Money is integer FCFA. Timestamps UTC.
10. No PII (names, phone numbers, message text) in logs or error reports.

## External services
Meta WhatsApp Cloud API, MTN MoMo Collections, and the AI provider are each wrapped behind an interface with a fake implementation for tests. **Tests never call real external APIs.**

## Working rules
- Build one slice at a time (see order below). Don't start the next slice unasked.
- Ask before adding a dependency.
- Every invariant above gets a test. Concurrency invariants get a real concurrent test against Postgres, not a mock.
- Reference requirement IDs in commit messages and test names where relevant.
- Keep responses short: show diffs and decisions, not restated requirements.

## Build order
1. Scaffold, data model, migrations, ledger, acceptance transaction + concurrency test
2. Job runner
3. Webhook ingress, message persistence, outbound sender (fake Meta)
4. Intake, AI interface (fake), confirmation, abuse controls
5. Dispatch waves, acceptance flow, contact release
6. Payments (MoMo sandbox), free credits
7. Follow-up, ratings, bad-lead refunds
8. Operator admin (`sqladmin`), metrics queries

## Current status
Slice 2 complete — job runner with handler registry, retry/backoff, dead state, transactional enqueue. 14 tests passing.

## Commands
```bash
# Setup (first time)
pip install -e ".[dev]"

# Run tests (requires Docker Desktop running)
DOCKER_HOST="npipe:////./pipe/dockerDesktopLinuxEngine" python -m pytest tests/ -v

# Run migrations against a database
alembic upgrade head

# Run web server (not yet wired)
uvicorn fixam.main:app --reload

# Run worker
python -c "import asyncio; from fixam.worker import main; asyncio.run(main())"
```
