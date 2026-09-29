# ITSM NL2SQL Platform

NL2SQL platform over ITSM ticket data: plain-English questions → safe, read-only SQL with a
semantic layer.

A service manager asks a question such as *"which assignment groups breached SLA most last
month?"*. The platform writes the SQL, runs it **read-only**, and answers in plain English —
**with the SQL shown**, so the answer can be trusted and checked.

## Status

| Stage | What | Status |
|---|---|---|
| Day 1 | ITSM database, synthetic data, naive "question → SQL" spike | ✅ Built — spike not yet run (OpenAI account needs credits) |
| Day 2 | Semantic layer (`meta_*` catalog) | 🟡 In progress — columns, metrics, glossary done; table and join descriptions to do |
| Day 2 | Evaluation set (accuracy) | ⬜ Planned |
| Day 2–3 | NL2SQL agent loop with guardrails | ⬜ Planned |
| Day 3 | HTTP API (FastAPI `/ask`) | ⬜ Planned |
| Day 4 | Web UI (Streamlit) | ⬜ Planned |

## Quick start

Requires Python 3.11+ (SQLite 3.37+ ships with it).

```bash
pip install -r requirements.txt
python db/seed.py                   # build db/tickets.sqlite with the sample data
python semantics/build_catalog.py   # add the semantic layer (run after every seed)
```

For large-scale testing, build a separate 50,000-incident database (about 3 seconds):

```bash
python db/seed.py --incidents 50000 --changes 10000 --out db/tickets_large.sqlite
python semantics/build_catalog.py --db db/tickets_large.sqlite
python evals/run_evals.py --golden evals/golden_set_large.yaml
```

To run the Day 1 spike, which calls the OpenAI API:

```bash
cp .env.example .env                # then set OPENAI_API_KEY in .env
python agent/naive_spike.py
```

`.env` and the `db/*.sqlite` databases are gitignored and never committed.

## Project structure

```
.
├── db/
│   ├── schema.sql            # 5-table SQLite schema: keys, constraints, indexes
│   └── seed.py               # deterministic synthetic data → db/tickets.sqlite
├── semantics/
│   └── build_catalog.py      # builds the meta_* semantic layer inside the database
├── agent/
│   └── naive_spike.py        # Day 1 spike: question → OpenAI → SQL, no context, no guardrails
├── evals/                    # accuracy test set                 (planned)
├── api/                      # FastAPI service                    (planned)
├── ui/                       # Streamlit front end                (planned)
├── CLAUDE.md                 # detailed project memory and handoff notes
└── requirements.txt
```

## The data

Five tables: `incidents`, `changes`, `sla_targets`, `assignment_groups` (teams) and `users`.
Incidents and changes belong to a team; each incident's priority links to its SLA target.

The sample data is synthetic and **identical on every run** (fixed seed, fixed "today" of
**28 Sep 2026**, so "last month" means August 2026):

- 5 teams, 40 users, 500 incidents over 6 months, 100 changes
- Exactly **15% of resolved incidents breach their SLA**, unevenly across teams
- Priority scale used everywhere:

| Priority | Also called | SLA target |
|---|---|---|
| 1 | P1, Sev1, Severity 1, Critical, urgent fix | 4 hours |
| 2 | P2, Sev2, Severity 2, High | 8 hours |
| 3 | P3, Sev3, Severity 3, Medium | 2 days |
| 4 | P4, Sev4, Severity 4, Low | 5 days |

An **SLA breach** is a resolved incident whose time from opened to resolved exceeds its target
(wall-clock time).

## The semantic layer

The Day 1 spike shows why sending a bare question to a language model fails: it invents table
names, uses the wrong SQL dialect and guesses what "breach" means. The semantic layer gives the
agent the missing context, stored as `meta_*` tables inside the database:

- **`meta_columns`** — every column described, with examples, synonyms, and flags for personal
  data and ambiguous meaning
- **`meta_metrics`** — `mttr`, `sla_breach_rate`, `reopen_rate` as reusable SQL, so formulas are
  defined once and never re-invented by the agent
- **`meta_glossary`** — business vocabulary ("P1", "team", "missed SLA", "last month") mapped
  to SQL, including terms the data cannot answer (e.g. "assignee") so the agent says so instead
  of guessing

The build checks itself and fails loudly: every stored SQL fragment runs, every reference
exists, no phrase maps to two meanings, and plural phrases ("tickets", "P1s") resolve correctly.

## Safety rules

The finished platform will enforce: **read-only** access · **SELECT-only** queries ·
**automatic row LIMIT** · **no personal data** in answers.

## Tech stack

Python · SQLite (portable to Postgres/Snowflake later) · OpenAI API at runtime.
`db/` and `semantics/` use the standard library only. `httpx` is pinned to 0.27.2 because the
pinned `openai` 1.51.2 breaks on newer versions.

## Training programme

This project is built over four days **with Claude Code** — directing an AI coding assistant to
build real software is the skill being taught. The running application itself calls the OpenAI
API. Day 1 is the on-ramp: stand up the database, explore it in plain English, try the simplest
"question → SQL" approach, and write down why it falls short. The rest of the week fixes that
list.
