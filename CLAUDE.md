# CLAUDE.md — Project memory

**What this is:** an **NL2SQL platform over ITSM ticket data**. A service manager types a
plain-English question ("which assignment groups breached SLA most last month?"); the system
writes SQL, runs it **read-only**, and answers in plain English — **with the SQL shown** for trust.

**Build tool vs runtime (keep these separate):**
- We **BUILD** this platform **with Claude Code** — that is the skill being taught.
- The **running app** calls a language model at runtime to generate SQL: **OpenAI** (default)
  or **Anthropic Claude**, chosen per question or by `LLM_PROVIDER` (`agent/llm.py`).

**Stack:** Python 3.11+ · SQLite 3.37+ (STRICT tables; swappable to Postgres/Snowflake later) ·
stdlib where possible. `db/` and `semantics/` are stdlib only. `requirements.txt` pins
`openai==1.51.2`, `anthropic==1.9.0`, `python-dotenv==1.0.1`, `pyyaml`, `httpx==0.27.2`,
`fastapi`, `uvicorn` and `pytest` (all exact pins; `pip check` clean). **Keep the httpx pin** while openai is 1.51.2: httpx 0.28+
makes `OpenAI()` crash with `unexpected keyword argument 'proxies'`. Drop the pin only if openai
is upgraded (to 1.55.3 or later).

**Current objective (2026-09-30):** end-product build done — multi-model agent, FastAPI
backend, React UI with a UI-vs-database check, pytest suite. The Streamlit UI was removed on
2026-09-30 (React is the only front end). Next: the open items below.

## Build and run (in this order)

```
python db/seed.py                   # recreates db/tickets.sqlite from db/schema.sql + synthetic data
python semantics/build_catalog.py   # adds the meta_* semantic catalog to db/tickets.sqlite
python agent/nl2sql.py "question"   # NL2SQL agent: catalog context -> OpenAI -> guarded SQL -> rows
python evals/run_evals.py           # score the agent on evals/golden_set.yaml (--json, --self-test, --golden)
python agent/naive_spike.py         # Day 1 naive spike (no context; shows why the agent is needed)
python run_app.py                   # API :8000 (/docs), React UI at :8000/web/, Ctrl+C stops it
cd web && npm run build            # React UI -> web/dist, served by the API at /web/ (npm run dev: :5173)
python -B -m pytest tests -p no:cacheprovider   # 130 tests, no API key, temp DB outside repo
cd web && npm run e2e              # 22 Playwright checks in Edge; starts its own API on :8010 (E2E_PORT=8000 reuses a running one)
```

Slash commands: `/smoke` (rebuild + checks), `/build-catalog` (rebuild catalog, report
undocumented entries), `/run-evals` (accuracy + 2 worst failures), `/build-large [N M] [live]`
(seed + catalog + golden_set_large.yaml + self-test for the large DB in one go; default
50000/10000, where golden_set_large.yaml must come out unchanged; `live` adds a live eval run). Skill:
`.claude/skills/diagnose-eval-failure/` (maps failed evals to the meta_* entry to fix).

`seed.py` deletes and recreates the database file, which also wipes the meta_* tables, so
always run `build_catalog.py` after it. `/smoke` (`.claude/commands/smoke.md`) rebuilds the
database, prints row counts and reports pass/fail.

**Runnable status (2026-09-29):** everything runs end to end. Dependencies installed
(`pip install -r requirements.txt`, `pip check` clean, Python 3.12 user site). `.env` holds
`OPENAI_API_KEY` (gitignored; never print or commit it) and the OpenAI account has credits.
- `run_evals.py --self-test` (no API): **50/50** on both golden sets (2026-09-30, after the set
  grew from 15 to 50). Earlier trap check: fed deliberately wrong SQL, scoring caught 12 of 14
  traps; the 2 misses are golden-set limits (see Evals below), not scoring bugs.
- **Live eval (gpt-4o-mini, temperature 0), 50 questions: 50/50 on both sets on the third run
  (2026-09-30)**; the first two runs were 47–48/50, see the Evals section for what each miss was.
  On the original 15 questions: 15/15 on three consecutive runs (was 13/15 before the catalog
  fixes listed under Evals).
- Naive spike first real output confirms the Day 1 failure modes: invented table
  `sla_breaches`, Postgres `DATE_TRUNC`/`INTERVAL`, real clock `CURRENT_DATE`, breach assumed
  to be stored.

**Git:** branch `main`, first commit 2026-09-29 (history before that lives only in this file).
Remote `origin` = **https://github.com/Mital-Bhalani/itsm-nl2sql-platform** (**public**;
recreated 2026-09-29 with a cleaned history so no employer name appears in any commit). On
2026-09-30 the local `.git` was found empty (no commits, no remote); `origin` was re-added,
fetched, and local `main` was reset (`--soft`) onto `origin/main` so history is shared again.
Commit and push only when the user asks; never force-push. The user's VS Code GitHub login (git
credential helper) can create and push but not delete repos; the GitHub CLI (`gh`) is not
installed. Commit author: `Mital-Bhalani <meetbhalani666@gmail.com>` (repo-local git config
only, set again 2026-09-30). Because the repo is public, scan staged changes for secrets and
employer/client names before every push. Never commit `.env` (API key) or `db/*.sqlite`; both
are gitignored.

**Safety posture the platform will enforce (aspirational on Day 1, built Day 2+):**
read-only · **SELECT-only** · auto-LIMIT · **no raw PII in output** (`users.name` is PII).

## Working rules for this repo

- Create only the files asked for, with exactly the names asked for; code files are `.py`.
- Never leave `__pycache__`/`.pyc` or other side files: run checks with `python -B`, put temp
  databases and scratch scripts outside the repo.
- When changing a description or definition, change one entry, show the before/after diff,
  and only then roll it out to the rest of the project.
- Flag ambiguous meanings (`is_ambiguous` + note) instead of guessing.

## Folder map and status

| folder | day | status |
|---|---|---|
| `db/` | 1 | **done**: `schema.sql`, `seed.py`, generated `tickets.sqlite` (gitignored `*.sqlite`); `dialect.py` (SQLite/PostgreSQL date expressions) |
| `agent/` | 1 → 2–3 | `naive_spike.py`, **`nl2sql.py`** (agent: `translate`, `ask`), **`llm.py`** (providers) |
| `semantics/` | 2 | **done**: `build_catalog.py` fills all five meta_* tables |
| `evals/` | 2 | **done**: `golden_set.yaml` (80 questions) + `run_evals.py` + `make_golden_set.py` |
| `api/` | 3 | **done**: FastAPI (`main.py`, `services.py`, `schemas.py`, `config.py`, `state.py` = SQLite store for rate limits and eval jobs) |
| `web/` | 4 | **done**: React 19 + TS + Tailwind 4 + TanStack Query + Recharts; built to `web/dist`, served at `/web/` |
| `End-to-End/` | — | **done**: 11-chapter project guide (hierarchy, every script/component, request lifecycle, security, operations); update it when code changes |
| `tests/` | — | **done**: pytest, 130 tests (guardrails, SQL lint, providers, dialect, API with a fake model, state store, security attacks) + `web/e2e` Playwright (22) |

`scripts/`, `docs/` and `spike/` from the original plan were not created: the data generator
lives in `db/seed.py` and the spike in `agent/naive_spike.py`. There is no `db/build_db.py`.

**Naive spike (`agent/naive_spike.py`)** — deliberately no schema context, no guardrails, no
validation, no execution. Sends the hard-coded question "which assignment groups breached SLA
most last month ?" to OpenAI (`OPENAI_MODEL`, default `gpt-4o-mini`) and prints the reply.
Reads `OPENAI_API_KEY` from the project-root `.env`. Its purpose is to show the failure modes
(invented table names, wrong dialect, wrong breach definition) that Day 2+ fixes.

## Database (`db/schema.sql`)

Five tables: `assignment_groups` (teams), `users`, `sla_targets` (minutes per priority),
`incidents`, `changes`. Joins:
- `incidents.assignment_group_id`, `changes.assignment_group_id`, `users.assignment_group_id`
  → `assignment_groups.id` (users' group is NULL for managers/admins)
- `incidents.priority` → `sla_targets.priority`
- No link incidents → users (no assignee/caller) and none incidents → changes.

Conventions: timestamps are TEXT `'YYYY-MM-DD HH:MM:SS'` UTC; status/risk/role are CHECK lists;
every connection must run `PRAGMA foreign_keys = ON`; tables are STRICT.

**Priority vocabulary (confirmed 2026-09-28; severity = priority):**

| priority | users say | SLA target |
|---|---|---|
| 1 | P1, Priority 1, Sev1, Severity 1, Critical, urgent fix | 240 min (4 h) |
| 2 | P2, Priority 2, Sev2, Severity 2, High | 480 min (8 h) |
| 3 | P3, Priority 3, Sev3, Severity 3, Medium | 2880 min (2 d) |
| 4 | P4, Priority 4, Sev4, Severity 4, Low | 7200 min (5 d) |

Single source for this wording: `PRIORITY_LEVELS` in `semantics/build_catalog.py` (column
descriptions, synonyms and glossary terms are generated from it); `db/schema.sql` header
comment mirrors it.

**Key definitions:**
- **SLA breach** = Resolved/Closed incident with
  `(julianday(resolved_at) - julianday(opened_at)) * 1440 > target_minutes`. Wall-clock, no
  pause for On Hold; not stored as a column.
- **Open** = status `New`, `In Progress`, `On Hold` (not `resolved_at IS NULL`, which also
  catches Cancelled).
- `resolved_at` is set iff status is Resolved/Closed; a reopen clears it and increments
  `reopened_count`.

## Sample data (`db/seed.py`)

Deterministic: `random.Random(42)` and fixed anchor **NOW = 2026-09-28 00:00 UTC** (a Monday).
"Today", "last month" (= August 2026) etc. are relative to this date, not the real clock.

Expected output (verified identical across runs): 5 groups · 40 users (31 agents, 5 team
leads, 3 managers, 1 admin) · 4 SLA targets · 500 incidents · 100 changes (90 past, 10 in
the next 28 days) · 649 rows total.
- Priority mix P1 17 / P2 63 / P3 275 / P4 145 (weights 5/15/50/30, drawn randomly).
- 440 Resolved/Closed, 50 open, 10 Cancelled; **SLA breach exactly 66/440 = 15.0%**,
  weighted toward Network (17/77) and Database (14/60); Service Desk lowest rate (13/150).
- August 2026 (opened in Aug, reference answer): breaches by count Service Desk 4, Network 3,
  Database 2, Application Support 1, Infrastructure 0 — but by rate Database is highest
  (28.6%). Count vs rate give different rankings; keep both as eval cases.
- Reopen rate 44/500 = 8.8%; MTTR ≈ 2,828.8 min.
- Changes risk mix Low 49 / Moderate 32 / High 19. The first two future changes (ids 91 and 92
  at the default size) are **pinned** to High risk, Scheduled, 4-hour windows
  (`PINNED_HIGH_RISK_STARTS` in `seed.py`): 2026-10-01 21:00 (as-of week) and 2026-10-07 21:00
  (following calendar week), so "high-risk changes next week" has data under either reading.
  Pinning adds no random draws; all other rows are unchanged.

**Large dataset (2026-09-29).** `seed.py` takes `--incidents`, `--changes`, `--out`; counts
scale with the same ratios (88% resolved/closed, 2% cancelled, rest open; 90% past changes;
exact 15% breach); users stay 40. With no arguments the output is **identical** to before
(verified by hash). Build the large set with:
```
python db/seed.py --incidents 50000 --changes 10000 --out db/tickets_large.sqlite   # ~3 s, 11 MB
python semantics/build_catalog.py --db db/tickets_large.sqlite                     # ~0.5 s
python evals/make_golden_set.py --db db/tickets_large.sqlite --out evals/golden_set_large.yaml
python evals/run_evals.py --golden evals/golden_set_large.yaml   # DB read from the YAML
python agent/nl2sql.py --db db/tickets_large.sqlite "question"
```
Verified: 50,000 incidents / 10,000 changes, breach 6,600/44,000 = 15.0%, open 5,000 (10%),
deterministic, FK/integrity clean; self-test 50/50; **live 50/50** (2026-09-30); slowest reference query
257 ms (J03); `LIMIT 1000` capped a 42,364-row query. At this scale K01 (teams with zero
breaches → no rows) and K02 (Network cancelled → 173) lose their "zero" edge; they are still
valid tests. `db/tickets_large.sqlite` is gitignored; `golden_set_large.yaml` is committed.
`evals/make_golden_set.py` generates both golden sets (defaults reproduce `golden_set.yaml`
byte-identically).

## Semantic catalog (`semantics/build_catalog.py` → meta_* tables in `tickets.sqlite`)

| table | rows | content |
|---|---|---|
| `meta_columns` | 23 | type, nullability, keys, FK, allowed values (read from schema.sql) + drafted description, example, `is_pii`, `is_ambiguous`/note, `synonyms` |
| `meta_metrics` | 3 | `mttr` (minutes), `sla_breach_rate`, `reopen_rate` (ratio 0–1) as reusable SQL fragments |
| `meta_glossary` | 51 | business terms → entity / value / metric / time / concept, with `sql_hint` |
| `meta_tables` | 5 | description and grain per data table (`TABLE_DRAFTS`) |
| `meta_joins` | 4 | one row per schema foreign key, with cardinality and pitfalls (`JOINS`); build fails if they drift |

- Metric composition: `SELECT <sql_expression> FROM <base_table> <base_alias>
  <required_joins> WHERE <filters> [AND question filters on <time_column>]`. All use alias `i`,
  `time_column = i.opened_at`. Formulas live in the catalog, never inline in the agent.
- Glossary aliases: `i` incidents, `c` changes, `g` assignment_groups, `u` users,
  `s` sla_targets. Placeholders: `{time_column}`, `{n}` (e.g. "severity 2" → 2).
- Build checks (script exits on failure): every referenced column/metric exists; every
  `sql_hint` executes; no synonym is claimed by two unflagged terms; examples match CHECK lists;
  16 plural/variant phrases in `LOOKUP_CHECKS` resolve to the right term.
- **Term lookup for the agent:** use `find_term(conn, phrase)` from `build_catalog.py`. It
  matches term names and synonyms case-insensitively, first as written, then with each word
  made singular by `singular()` ("tickets" → incident, "P1s" → critical priority, "high-risk
  changes" → high-risk change; "status", "analysis", "sla" are left alone). Plurals are handled
  here, not by adding plural synonyms to the glossary.
- Still flagged ambiguous — columns: `incidents.status` (Resolved vs Closed),
  `incidents.resolved_at` (latest resolution), `incidents.assignment_group_id` (which team),
  `sla_targets.target_minutes` (resolution vs response, business hours), `changes.risk`,
  `users.assignment_group_id`. Glossary: `closed` (default = Resolved or Closed), `overdue`
  (open and past target), `next week` (calendar week after the current one), `impact`.
- Not answerable from this data (`is_answerable = 0`): assignee, caller, response time,
  downtime, impact, actual change window, change-caused incident.

## Agent (`agent/nl2sql.py`)

`translate(question)` → `{terms, refusal, sql, assumption, unsafe}`; `run_sql(conn, sql)`.
1. Resolve question phrases (1–4 words, longest first) with `find_term()`.
2. A term with `is_answerable = 0` → refuse **before** any API call.
3. Prompt = rules + all meta_* content (tables, columns, joins, metrics, glossary) + the terms
   found; nothing about the schema is hard-coded. Model `OPENAI_MODEL` (default
   `gpt-4o-mini`), temperature 0; ambiguous terms → `-- assumption:` line.
4. **SQL lint** (`lint_sql`, added 2026-10-01): SQL that runs but is certainly wrong is sent back to
   the model once, then blocked (`unsafe`) if still wrong: an unknown date modifier (SQLite returns
   NULL for `'start of quarter'`, so a count silently became 0), two child tables (incidents,
   changes, users) joined in one aggregate query (join fan-out multiplies every count), and a
   filter on the parent table inside a `LEFT JOIN ... ON` (removes no rows). Join paths come from
   `meta_joins`; the golden-set reference SQL must lint clean (a test checks it). Also caught before
   running: SQL that SQLite rejects (`EXPLAIN`), so the repair call now happens inside `translate()`.
   **Soft checks** (`lint_question`, same 2026-10-01 round) compare the SQL with the question and
   trigger one repair call but never block: an open-status filter nobody asked for ("P1 incidents",
   "recently opened" is a date, not the status open), `status <> 'Cancelled'` nobody asked for,
   "show/list" answered with one aggregate (MIN/COUNT instead of rows), "how many teams..." answered
   with one row per team, "average number of X per Y" returned per group or divided by a fixed 12.
   Follow-up questions skip the soft checks. Glossary terms `median` and `running total` carry the SQL
   recipe (SQLite has no MEDIAN).
5. Guardrails: one SELECT/WITH statement, write/admin keywords rejected, DB opened read-only,
   `LIMIT 1000` appended if missing, `users.name` blocked by a SQLite authorizer (also via
   `SELECT *`). API failures raise `AgentAPIError`.

**`ask(question, conn, provider, model, answer=True)`** = full pipeline used by the API:
translate → run → on an SQLite error **one repair call** (error + failed SQL sent back) →
**plain-English answer** (second call with ≤50 rows; falls back to a fixed sentence if it
fails). Adds `answer, error, columns, rows, row_count, truncated, repaired, provider, model,
tokens_in/out, timings`. `run_sql` has a **5 s timeout** (progress handler).

## Model providers (`agent/llm.py`)

`complete(system, user, provider=None, model=None)` → `LLMReply(text, provider, model,
latency_ms, tokens_in, tokens_out)`. Providers: `openai` (default model `gpt-4o-mini`,
temperature 0) and `anthropic` (default `claude-opus-5-5`, effort `low`, system prompt marked
for prompt caching, server-side refusal fallback `fallbacks="default"`; current Claude models
reject `temperature`). Env: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_FALLBACK_PROVIDER`,
`OPENAI_API_KEY`/`OPENAI_MODEL`, `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL`. Fallback applies only
when no provider was requested explicitly. All failures raise `AgentAPIError` (re-exported by
`nl2sql`). `anthropic` 1.x uses `httpx2`, so it does not conflict with the `httpx==0.27.2` pin.
**Anthropic has not been run live yet** (no `ANTHROPIC_API_KEY` as of 2026-09-29); it is
covered only by mocked tests.

## API and UI (`api/`, `web/`, `run_app.py`)

- API endpoints: `/health`, `/api/models`, `/api/overview`, `POST /api/ask`, `/api/kpis`,
  `/api/groups`, `/api/tables[/{name}]` (filters `f_<col>`), `/api/incidents/{id}`,
  `/api/catalog/{section}`, `/api/reconcile`, `POST /api/sql`, `POST/GET /api/evals[/{id}]`
  (background thread, in memory). All take `dataset=default|large`. Details in `api/README.md`.
- KPIs are composed from `meta_metrics` fragments (no formulas in the API); breach count =
  rate × resolved. Verified against the seed facts (66/440, Aug counts 4/3/2/1/0).
- Security: `APP_API_KEY` → `X-API-Key` required on `/api/*`; rate limit on `/api/ask` and
  `/api/sql` (`RATE_LIMIT_PER_MIN`, default 30); audit log `logs/audit.jsonl` (gitignored);
  explorer names whitelisted from `meta_columns`, values bound; `users.name` masked and
  authorizer-blocked.
- **Security hardening (2026-09-30)**, each attack a test in `tests/test_security.py`:
  (1) `SELECT * FROM pragma_database_list` in the SQL console returned the server's full file
  path (the regex guard only blocks the word `pragma`, not `pragma_*` functions) - the authorizer
  is now an **allow-list** (SELECT, READ, FUNCTION, RECURSIVE; `load_extension` denied);
  (2) a query's own `LIMIT 3000000` returned 3M rows - `run_sql` uses `fetchmany(MAX_ROWS)`;
  (3) `zeroblob`/`hex` built 400 MB values - `connect_readonly` sets `SQLITE_LIMIT_LENGTH` 1 MB,
  SQL length 100 KB, no ATTACH, `hard_heap_limit` 512 MB; (4) rate limit keyed on the
  caller-supplied `X-API-Key`, so rotating it bypassed the limit - now keyed on client IP, per
  bucket (ask, sql, evals, feedback); (5) any `model` string accepted (cost abuse) - allow-list
  `llm.allowed_models()` + `LLM_ALLOWED_MODELS`; (6) OpenAI auth errors echo part of the key -
  `llm.redact()`; (7) eval runs unlimited - rate limit + `MAX_RUNNING_JOBS = 2`; plus security
  headers and a CSP on `/web`, sanitised `X-Request-ID`, bytes-safe key compare, and `run_app.py` refuses a non-local `--host` without `APP_API_KEY`.
  Still open: the React UI has no login (keep it local); `/docs` and `/health` are public.
- UI talks only to the API. Sidebar: dataset, provider, model (kept across pages), connected
  DB file + last-changed time, **Refresh from database** (UI caches API answers 10 s).
  Ask page can **compare two models** side by side, draws a chart automatically, offers three
  follow-up questions (the answer call returns JSON `{answer, followups}`; `parse_answer`
  falls back to plain text) and records thumbs up/down via `POST /api/feedback`.
- Pages: Home, Ask, Dashboard (sparklines, period deltas, click-a-team drill-down to the
  explorer), Explorer, Incident (gauge, timeline, `/api/incidents/{id}/similar`), Catalog,
  Evals, Data check.
- **Streamlit UI removed (2026-09-30):** `ui/`, `.streamlit/` and the `streamlit` pin are gone;
  `run_app.py` starts only uvicorn; `CORS_ORIGINS` defaults to the Vite dev server (5173). The
  Streamlit code is still in git history before that date if ever needed.
- **UI polish (2026-09-30):** light/dark theme with a toggle in the top bar (top right on every
  page; stored in `localStorage`, OS preference on first visit, `?theme=dark|light` override);
  all colours go through semantic tokens in `web/src/index.css` (`bg-surface`, `text-ink`,
  `border-line`, `bg-tone-*` …; `@custom-variant dark` on the `dark` class of `<html>`, set in
  `main.tsx` before first paint); responsive shell (sidebar becomes a drawer below `lg`, top bar
  with menu button); fast page switches (`web/src/routes.ts` prefetches every page chunk in idle
  time and on link hover, `gcTime` 10 min, 180 ms fade-in). Checked with headless Edge shots in
  both themes; note Chromium's headless window cannot go below ~500 px wide, so phone widths
  were checked at 500 px. Pitfall found: a `@utility text-tone-ok` clashed with the
  `--color-tone-ok` theme colour (same generated class name), so tones are plain `@utility`
  rules, not theme colours.
- **React UI (`web/`, 2026-09-29):** hash routes, same-origin API calls
  (Vite dev proxy / FastAPI `StaticFiles` mount at `/web`, `/` redirects there). Node 24 LTS
  installed system-wide with winget (first attempt without admin used a portable copy, since
  removed). Checked with headless Edge screenshots (`msedge --headless=new --screenshot`).
  Bugs found that way: (1) **API connections crossed threads** (FastAPI opens the dependency
  and runs the endpoint on different workers; parallel React requests gave HTTP 500) - fixed
  with `connect_readonly(check_same_thread=False)` in `services.connect`, regression test
  `test_connection_works_across_threads`; (2) React effect returned `scrollIntoView()`'s
  Promise (newer Chromium) and crashed the page - effects use braces; (3) Recharts
  animations never finish headless - `isAnimationActive={false}`. `web/` sits in OneDrive:
  `node_modules` syncs too (small, 67 packages).
- **UI ↔ database check** (Data check page, `/api/reconcile`): 25 checks compare every
  number the UI shows with SQL written separately from `meta_metrics` (`services.DIRECT_CHECKS`,
  from the schema-header definitions); 25/25 on both datasets. `/api/sql` = user SQL console
  through `guard_sql` + `run_sql`. The API opens the database per request, so changes show up
  live (a test inserts a row and sees it without restart).
- `run_app.py` sets `PYTHONDONTWRITEBYTECODE=1`; binds 127.0.0.1 by default.

## Evals (`evals/golden_set.yaml`, `evals/run_evals.py`)

`--provider` / `--model` score another model; the JSON report records them. Live OpenAI after
the provider refactor: 15/15 (2026-09-29); after growing the set to 50: **50/50 on both golden
sets** (2026-09-30, third run). After the 2026-09-30 improvement round (51 questions, final rule wording):
**51/51 on both golden sets, two consecutive runs each** (four runs, zero misses).

**51 questions** (12 easy lookups, 13 date ranges, 14 multi-table joins, 12 edge cases incl.
two refusals). The first 15 (E01–E04, D01–D04, J01–J04, K01–K03) date from the original build;
**35 were added 2026-09-30** (E05–E12, D05–D13, J05–J14, K04–K11), each grounded in a seed fact
(see the `notes` in `make_golden_set.py`): plural wording ("open tickets", "which teams"), the
schema-header example questions (MTTR by priority, reopened more than once, high-risk changes
next week per team, agents per group), other time columns (`planned_start`, `resolved_at`),
"overdue" vs "breach", rate vs count rankings (J06), zero answers (cancelled P1, opened in 2025,
opened last month and still open), a non-existent team (K05, 0 or no rows), month labels
(D06 accepts `YYYY-MM` or `MM`), minutes-or-hours alternatives for MTTR, and a second refusal
(response time). D11 is the "next week" case whose two readings return different rows. Both
golden sets self-test 51/51. K12 ("incidents assigned to the Network team", 83) is the
regression for the false refusal fixed on 2026-09-30. Expected rows come from running each `reference_sql`; regenerate
both files with `make_golden_set.py` if `seed.py` changes. Scoring: order-insensitive unless `order_matters`; numeric `tolerance`;
extra result columns allowed if a subset matches; `alternatives` accepted for ambiguous
questions; refusal questions pass only on refusal. Statuses `pass|wrong_result|sql_error|
unsafe|no_sql`; `--json` prints the object `/run-evals` reads. API failure stops the run
(exit 2) instead of counting as wrong answers.

Known golden-set limits: D01's "real clock" trap is only caught from 2026-10-01 (today's real
month equals the as-of month); E02's "`resolved_at IS NULL` = open" trap is not caught (no
cancelled P1 rows); D02's two readings both return 1.

**Live accuracy history (gpt-4o-mini, temperature 0):** 13/15 → **15/15 on three consecutive
runs (2026-09-29)** after these catalog fixes (no agent code changed):
- `meta_metrics[sla_breach_rate].notes`: rate/percentage questions → `ROUND(100.0 * expr, 1)`;
  "how many / most breaches" → the count, never ×100. (Fixed J02; the first wording, "always a
  percentage", broke J01 by scaling counts.)
- `meta_joins[incidents.assignment_group_id → assignment_groups.id].notes`: join teams only
  for per-team answers; conditions on incidents and the `sla_targets` join go inside the LEFT
  JOIN; count with `COUNT(i.id)`, never `COUNT(*)`. (Fixed K01; the unscoped first wording broke
  D04; the COUNT rule fixed an intermittent K02 failure: `COUNT(*)` returned 1 instead of 0.)
- `meta_glossary['SLA breach'].definition`: time windows filter `i.opened_at`.
- `meta_glossary['resolved incident'].definition`: "resolved <window>" filters `i.resolved_at`.

- 2026-09-29, unneeded join: "incidents for each priority" joined `assignment_groups` for no
  reason. A catalog-only fix (`meta_tables[incidents].description`: totals/breakdowns by
  priority, status or date read incidents alone) changed nothing (3/3 still joined). Cause:
  the hard-coded prompt rule in `agent/nl2sql.py` ("When listing per team, start FROM
  assignment_groups…"). Reworded it to apply only when the result has one row per team; that
  first rewording broke K01 5/5 (date filter moved to WHERE), so the rule now also says filters
  on joined tables go in the LEFT JOIN's ON clause and "zero X" uses HAVING. Result: K01 5/5,
  no unneeded joins, 15/15 twice on both golden sets.

**Growing the set to 50 (2026-09-30), what the three live runs showed** (agent and catalog
unchanged; only the golden set was corrected where the reference was the problem):
- K05 first read "How many incidents are **assigned to** the Security team?": `find_term` matched
  "assigned to" (a synonym of the unanswerable term *assignee*) and the agent refused before any
  model call. A real false-refusal risk for wording like "tickets assigned to Network"; reworded
  the question ("does the Security team have") and logged it as open item 10.
- J13 "resolve within SLA last month": the model filters `resolved_at` (the catalog's "resolved
  <window>" rule) while the first reference used `opened_at`; made `resolved_at` the primary
  reading and kept `opened_at` as an alternative (20 vs 19 at the default size).
- D07 "high-risk changes planned this month": the model excludes Cancelled and stops at the
  as-of date (glossary "this month"); the reference counted the whole calendar month with
  cancelled included. Identical (3) on the default set, different on the large one, so the
  large run caught it. Now three accepted readings.
- K07 "teams with no open P1 incidents" failed once with `status IN ('New', 'In Progress')`
  (On Hold dropped; the only open Service Desk P1 is On Hold) and passed on the other runs. A
  genuine intermittent agent miss, kept as-is; if it recurs, strengthen the "open" definition
  (glossary `open incident` / `meta_columns[incidents.status]`).
- E08 "which incidents were reopened more than once" returned 1,100 ids on the large set and
  hit `LIMIT 1000`; changed to a count so the question works at both sizes.

**Improvement round (2026-09-30, after the 50-question set)**, all verified (pytest 83, e2e 22,
self-test 51/51 both sets):
- **False refusal fixed**: "assigned to" removed from the *assignee* synonyms (now "assigned
  person, assigned engineer, who is working on, ..."); "incidents assigned to Network" answers 83.
  Eval K12 guards it.
- **"Open" = all three statuses**: after three wordings (see the rule-wording note below) the
  fix that held is a clause on the existing hint rule in `build_context`: "do not invent
  formulas or shorten status lists (an open incident is always i.status IN ('New', 'In
  Progress', 'On Hold'), all three)", plus the same sentence in the glossary `open incident`
  definition. Reopen-rate notes carry the same percentage convention as breach rate (open
  item 1 closed).
- **Conversation memory**: `nl2sql.ask/translate(history=[{question, sql}])`; the last 3 turns go
  into the USER message under "CONVERSATION SO FAR" (system prompt unchanged, so the provider
  cache still hits). API: `AskRequest.history` (max 5 turns, 422 beyond). React Ask page sends
  the thread's last 3 SQL-producing turns; Clear resets. Verified live: "and by team?" after
  "How many P1 incidents are currently open?" kept priority = 1 and all three open statuses.
- **Prompt cost / latency measured**: OpenAI caches the catalog prefix automatically: 4,224 of
  ~4,400 prompt tokens cached from the second call on (`LLMReply.tokens_cached`, also summed
  into the ask result). Cached calls take 1.2–1.8 s. The slow first calls (20–52 s) are
  provider-side and happen even with a cached prefix and after `llm.warm_up()`; the SDK client is
  now built once per provider and reused (`llm._client`, `reset_clients()`), and the API warms it
  in a thread at startup, but that removes only the local part of the delay.
- **State store** `api/state.py` (`STATE_DB`, default `logs/state.sqlite`, WAL): rate-limit hits
  and eval jobs, shared across processes; jobs persist across restarts; `MAX_RUNNING_JOBS`
  counted from the store; stale running jobs (>30 min) marked failed. `GET /api/evals` lists
  stored runs; `GET /api/evals/history?golden=&limit=&mode=` gives per-question pass rates and
  failures. Evals page shows recent runs and flaky questions.
- **As-of date is a build setting**: `AS_OF=YYYY-MM-DD|today python semantics/build_catalog.py`
  writes `meta_settings(as_of, dialect, built_at)`; the agent (`catalog_as_of(conn)`) and the
  API read it from the connected database, nothing hard-codes 2026-09-28 at runtime any more
  (the golden sets still assume the sample date).
- **Dialect layer** `db/dialect.py` (stdlib): `minutes_between`, `date_from`, `month` for
  SQLite and PostgreSQL; `build_catalog.py`, `services.py` and the prompt's dialect line use
  it. SQLite catalog text verified byte-identical before/after.
  PostgreSQL output is **not** run against a server yet; the read-only connection, authorizer
  and limits are still SQLite-only.
- **CI**: `.github/workflows/ci.yml`: Python job (pip check, seed + catalog for both sizes,
  golden sets regenerate byte-identical, both self-tests, pytest) and web job (npm ci, lint,
  build, then boots the API and checks `/web/` and `/api/reconcile`). Playwright is not in CI
  (needs Edge/Chromium download); run `npm run e2e` locally.
- **React UX**: drawer focus trap + Escape; saved questions (star on an answer, chips on Ask,
  card on Home, localStorage `itsm-insights-saved`, max 20); ask bar no longer fixed at 288 px
  on phones.
- `streamlit` package uninstalled from the local environment (`pip check` clean).
- **Rule wording matters (again)**, three attempts at the On Hold rule, each verified live:
  (1) a standalone RULE "'Open' incidents are New, In Progress AND On Hold, always" made the
  model add a status filter to "incidents **opened** per month" (D06 failed on both sets);
  (2) rewording it to "'Open' as a STATUS ... 'Opened' is about the opened_at DATE" broke
  D06, D13 and J01 deterministically (invented 30-day and '-2 month' windows, HAVING > 0);
  (3) removing the standalone rule and adding one clause to the existing "use hints exactly"
  rule passed every probe (J01, D01, D06, D13, E02, E05, J03, K07, K08 and D11 large).
  A new standalone rule changes behaviour across the whole set; a clause on an existing rule
  is far safer. Also: D11 on the large set once read "scheduled next week" as
  `status IN ('Scheduled', 'Implement')`; new glossary term **`scheduled for`** (synonyms
  scheduled in, planned for/in, booked for, due in): window on `planned_start`,
  `status <> 'Cancelled'`, never `status = 'Scheduled'`. Glossary is now 43 terms.

Lessons: the agent's prompt RULES outrank catalog notes — if a catalog fix has no effect, look
for a conflicting rule in `build_context`. Catalog wording generalises — fix narrowly, re-run
the **whole** set, and repeat runs
(the model is not fully deterministic even at temperature 0). 15/15 on 15 questions written
alongside these fixes is not proof of general accuracy; grow the golden set (open item 3).

**Probe round (2026-10-01): 95 new questions with separate reference SQL, run live (gpt-4o-mini).**
66 passed; 18 gave a wrong or invented answer with no warning. Fixed deterministically (no prompt
rule added): invalid date modifier (`SQL lint`; new glossary terms `last quarter`, `this quarter`
with literal dates), join fan-out and parent-filter-in-LEFT-JOIN (`SQL lint` + one repair call),
inverted "SLA compliance rate" (new glossary term `SLA compliance`: 85.0, not the 15.0 breach rate),
and questions the data cannot answer that used to be answered (new not-answerable terms
`escalation`, `forecast`, `agent activity`). Eleven regression questions added (D14, D15, J15-J18,
K13-K17); the set is 62. Live: **61/62 on both sets**; the miss is J16 ("incidents per team per
agent" returns the two counts, not the ratio; the numbers are correct). A glossary term `per agent`
was tried for J16 and made the model write invalid SQL (HAVING on a non-aggregate query), so it
was reverted. Still open from the probe (real but rarer, left alone): median is computed as a
mean (A01), no running totals (J20), invented filters or shapes (V14 adds an open-only filter,
O01-O03), "last 7 days" covers 6 days (T03), cancelled changes dropped without being asked
(T13, J10), `HAVING` counts returned per team instead of one number (J16 probe variant).

**Second probe round (2026-10-01): 78 more questions** (changes table, phrasing, typos, French and
German, follow-ups with history, hostile input): 72 passed. All 10 hostile probes (SQL injection,
prompt and key extraction, PII, writes) and the follow-ups passed. Misses: invented filters
(V14, O01, C06/T13/J10: open-only or cancelled-excluded nobody asked for), wrong shape (O02 returns a
date, O03/P25 a count instead of a list, J16 one row per team), wrong calculation (A01 median = mean,
J20 running total, P18 divides by a hard-coded 12, C04 per-team counts labelled an average).
**18 of them were added to the golden set before any fix** (E13-E16, D16-D19, J19-J24, K18-K21), so
the set is 80 questions. Live baseline: **63/80 default, 65/80 large**; the failing ones are these
new cases plus J16, J17 and the intermittent J07 ("agents per group" sometimes counts every user, not
only role agent). Not in the set because they need new not-answerable terms first: "which
category", "email address of the admin", "weather", "assigned to John". D18 fails on
translate() only (ask() repairs the syntax error), and the evals call translate().

**Fixes for the second-round cases (2026-10-01), measured on the 80-question set:** live gpt-4o-mini
went from **63/80 to 77/80 on the default database and 65/80 to 77/80 on the large one** (77 and 76 on the runs
before the J24 alternative, 77 and 77 after it; one run each, so repeat before trusting). Fixed by the soft lint and the two glossary terms above: E13-E16, D16,
D18, J19-J21, J24 (opened_at/resolved_at window accepted as an alternative, as for J13), K18-K21.
Still failing: **J16** ("incidents per team per agent": returns both counts, not the ratio; a
`per agent` glossary term made it worse, see above), **D19** ("between 9am and 5pm" is applied to
the as-of day only) and **J23** ("highest percentage of P1 incidents" is read as the team's share of
all P1 incidents). Intermittent, each passing in other runs: J07 (counts every user, not only role
agent), J01 (once invented the window `date('2026-08-28')`), J15.

## Open items / next steps

1. ~~Apply the percentage convention to `reopen_rate` too.~~ Done 2026-09-30.
2. Resolve the flagged ambiguities with the business (especially Resolved vs Closed).
3. ~~Add plural questions, a Cancelled-P1 case for E02, and different-answer readings of "next
   week" to the golden set.~~ Done 2026-09-30 (E05, K04, D11 among the 35 new questions).
4. Add `ANTHROPIC_API_KEY` and run `python evals/run_evals.py --provider anthropic` to get a
   real Claude score (not yet measured).
5. **Rotate the OpenAI key**: it was pasted into a chat session.
6. Optional: priority synonyms "urgent", "highest/lowest priority", "moderate/normal priority"
   were dropped when the vocabulary was standardised; re-add to `PRIORITY_LEVELS` if wanted.
7. Decide whether the spike should take the question as a CLI argument.
8. Production gaps still open: no Dockerfile (Docker not installed here); no user accounts/SSO
   (one shared API key, deliberately deferred); PostgreSQL dialect written but never run
   against a server (needs a connection factory, read-only role and statement_timeout in
   place of the SQLite authorizer); Playwright e2e not in CI. Closed 2026-09-30: CI on GitHub
   Actions, state store for rate limits and eval jobs, prompt caching measured (OpenAI caches
   the catalog prefix automatically), `AS_OF` is a catalog build setting.
9. 2026-09-29: CLAUDE.md was once overwritten on disk by an older version from outside the
   session (suspected OneDrive sync); restored from git. If it happens again, compare with
   `git show HEAD:CLAUDE.md` before editing.
10. ~~False refusal on "assigned to <team>".~~ Fixed 2026-09-30 (synonym dropped, eval K12).
11. First OpenAI call after a quiet period is sometimes 20–50 s even with a cached prefix and
   a warm client; later calls 1–2 s. Provider-side. If it matters, add a UI notice after 10 s
   or try a different model/region; `timings.llm_ms` in the ask result shows the split.

Closed gaps (2026-09-28): no High-risk change next week → pinned changes 91/92 in `seed.py`;
plural words missed by glossary lookup → `find_term()` / `singular()` in `build_catalog.py`.
