# CLAUDE.md — Project memory

**What this is:** an **NL2SQL platform over ITSM ticket data**. A service manager types a
plain-English question ("which assignment groups breached SLA most last month?"); the system
writes SQL, runs it **read-only**, and answers in plain English — **with the SQL shown** for trust.

**Build tool vs runtime (keep these separate):**
- We **BUILD** this platform **with Claude Code** — that is the skill being taught.
- The **running app** calls the **OpenAI API** at runtime to generate SQL.

**Stack:** Python 3.11+ · SQLite 3.37+ (STRICT tables; swappable to Postgres/Snowflake later) ·
stdlib where possible. `db/` and `semantics/` are stdlib only. `requirements.txt` pins
`openai==1.51.2`, `python-dotenv==1.0.1` and `httpx==0.27.2`; the spike currently needs only
`openai` (it parses `.env` itself). **Keep the httpx pin** while openai is 1.51.2: httpx 0.28+
makes `OpenAI()` crash with `unexpected keyword argument 'proxies'`. Drop the pin only if openai
is upgraded (to 1.55.3 or later).

**Current objective:** Day 2 — finish the semantic catalog, then evals and the agent loop.

## Build and run (in this order)

```
python db/seed.py                   # recreates db/tickets.sqlite from db/schema.sql + synthetic data
python semantics/build_catalog.py   # adds the meta_* semantic catalog to db/tickets.sqlite
python agent/naive_spike.py         # Day 1 naive spike (needs .env with OPENAI_API_KEY)
```

`seed.py` deletes and recreates the database file, which also wipes the meta_* tables, so
always run `build_catalog.py` after it. `/smoke` (`.claude/commands/smoke.md`) rebuilds the
database, prints row counts and reports pass/fail.

**Runnable status (end-to-end check, 2026-09-28):** seed, catalog build, FK/integrity checks,
determinism (two rebuilds identical) and catalog-driven SQL all **pass**. Dependencies are
installed (`pip install -r requirements.txt`, `pip check` clean; installed to the user site for
Python 3.12). `.env` with `OPENAI_API_KEY` now exists (gitignored; never print or commit it).
`/smoke` still does not check the key. The spike's live call reaches OpenAI and the key is
accepted, but it fails with **429 `insufficient_quota`** (`credit_balance_exhausted`): the
OpenAI account has no credits. That is a billing issue, not a project defect; the spike has
not yet produced output. Full check: 59 of 60 pass, the one failure being this billing block.

**Git:** local repository on branch `main`, first commit made 2026-09-29 (history before that
lives only in this file). Target GitHub repo: **`itsm-nl2sql-platform`** (private), published
and pushed through **GitHub Desktop** — the GitHub CLI (`gh`) is not installed, so Claude
commits locally and the user clicks Publish / Push origin in Desktop. Commit author:
`Mital-Bhalani <meetbhalani666@gmail.com>` (set in the repo's local git config only).
Never commit `.env` (API key) or `db/tickets.sqlite`; both are gitignored.

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
| `db/` | 1 | **done**: `schema.sql`, `seed.py`, generated `tickets.sqlite` (gitignored `*.sqlite`) |
| `agent/` | 1 → 2–3 | `naive_spike.py` written, **not yet run**; NL2SQL agent loop not started |
| `semantics/` | 2 | **in progress**: `build_catalog.py` (meta_columns, meta_metrics, meta_glossary filled) |
| `evals/` | 2 | not started; seed questions are at the bottom of `db/schema.sql` |
| `api/` | 3 | not started (FastAPI `/ask`) |
| `ui/` | 4 | not started (Streamlit) |

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
- Changes risk mix Low 49 / Moderate 32 / High 19. Changes 91 and 92 are **pinned** to High
  risk, Scheduled, 4-hour windows (`PINNED_HIGH_RISK_CHANGES` in `seed.py`): 2026-10-01 21:00
  (as-of week) and 2026-10-07 21:00 (following calendar week), so "high-risk changes next week"
  has 1 row under either reading. Pinning adds no random draws; all other rows are unchanged.

## Semantic catalog (`semantics/build_catalog.py` → meta_* tables in `tickets.sqlite`)

| table | rows | content |
|---|---|---|
| `meta_columns` | 23 | type, nullability, keys, FK, allowed values (read from schema.sql) + drafted description, example, `is_pii`, `is_ambiguous`/note, `synonyms` |
| `meta_metrics` | 3 | `mttr` (minutes), `sla_breach_rate`, `reopen_rate` (ratio 0–1) as reusable SQL fragments |
| `meta_glossary` | 42 | business terms → entity / value / metric / time / concept, with `sql_hint` |
| `meta_tables` | 0 | not populated yet |
| `meta_joins` | 0 | not populated yet |

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

## Open items / next steps

1. Populate `meta_tables` and `meta_joins`.
2. Resolve the flagged ambiguities with the business (especially Resolved vs Closed).
3. Build the eval set in `evals/` from the example questions (include count-vs-rate cases).
4. Build the NL2SQL agent loop in `agent/` using the catalog, with the safety posture above.
5. **Blocked on billing:** the OpenAI account has no credits. Add credits at
   platform.openai.com → Settings → Billing, then run `python agent/naive_spike.py` and record
   its output as the Day 1 failure example. (Rotate the key after the training: it was pasted
   into a chat session.)
6. Optional: priority synonyms "urgent", "highest/lowest priority", "moderate/normal priority"
   were dropped when the vocabulary was standardised; re-add to `PRIORITY_LEVELS` if wanted.
7. Decide whether the spike should take the question as a CLI argument.
8. Add plural questions ("how many tickets…", "which teams…") and both readings of "next
   week" to the eval set.

Closed gaps (2026-09-28): no High-risk change next week → pinned changes 91/92 in `seed.py`;
plural words missed by glossary lookup → `find_term()` / `singular()` in `build_catalog.py`.
