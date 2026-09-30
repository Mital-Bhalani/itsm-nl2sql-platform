# ITSM NL2SQL Platform

[![CI](https://github.com/Mital-Bhalani/itsm-nl2sql-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Mital-Bhalani/itsm-nl2sql-platform/actions/workflows/ci.yml)

**Ask your IT service data a question in plain English and get a checked answer back.**

A service manager types *"Which teams missed their SLA most last month?"*. The app finds the
answer in the ticket database and replies in a sentence, with a chart. It also shows exactly how
it got the number, so nobody has to take it on trust.

> **New here?** The [End-to-End guide](End-to-End/README.md) explains every folder, script and
> component from the database to the screens.

## In plain words

- **No SQL, no spreadsheets.** You ask in normal English; the app does the database work.
- **It shows its working.** Every answer comes with the database query behind it.
- **It cannot change anything.** The app can only read the data, never edit or delete it.
- **It protects people's data.** Staff names are hidden and cannot be pulled out by a question.
- **It says "I can't answer that"** when the data does not hold the answer, instead of guessing.

## How a question gets answered

```mermaid
flowchart LR
    Q["You ask a question<br/>in plain English"] --> D["Dictionary<br/>what our words mean<br/>e.g. P1 = priority 1"]
    D --> AI["AI model<br/>writes the database query"]
    AI --> G{"Safety check<br/>read-only? allowed?"}
    G -- "no" --> R["Refused, with the reason"]
    G -- "yes" --> DB[("Ticket database")]
    DB --> A["Answer in a sentence<br/>+ chart + the query used"]
```

The **dictionary** is the key idea. On its own, an AI model guesses what "breached SLA" or "P1"
means and often gets it wrong. The dictionary tells it the company's exact definitions, so the
same question always gets the same, correct answer.

## How it fits together

```mermaid
flowchart TB
    U["People<br/>(web browser)"] --> W["Screens<br/>React app"]
    W --> API["Service layer (API)<br/>login key · rate limit · audit log"]
    API --> AG["Question answerer<br/>dictionary + safety checks"]
    AG --> LLM["AI model<br/>OpenAI or Anthropic Claude"]
    AG --> DB[("Ticket database<br/>read-only")]
    API --> DB
```

The screens never touch the database directly; everything goes through the service layer,
which logs every question asked. Either AI provider can be used and swapped per question.

## Status

All eight days are done. Each day added one layer on top of the previous ones; the stack
column lists only what that day introduced.

| Day | What was built | Stack added | Status |
|---|---|---|---|
| 1 | ITSM database (5 tables), deterministic synthetic data, naive "question → SQL" spike | SQLite (STRICT tables), Python standard library, OpenAI SDK | ✅ Done |
| 2 | Semantic layer: `meta_*` catalog of columns, metrics, glossary, tables and joins, with self-checks | SQL fragments stored in SQLite (`meta_*` tables) | ✅ Done |
| 3 | Evaluation harness: 51-question golden set, scoring, self-test, 50,000-incident large dataset | PyYAML | ✅ Done |
| 4 | NL2SQL agent: catalog context, guardrails (read-only, SELECT-only, auto-LIMIT, PII block, timeout), one SQL repair, plain-English answers with follow-ups | OpenAI gpt-4o-mini, SQLite authorizer and progress handler | ✅ Done, 51/51 live |
| 5 | Multi-model: OpenAI and Anthropic Claude, switchable per question, with fallback | Anthropic SDK (Claude Opus 5.5), python-dotenv | ✅ Done |
| 6 | HTTP API: ask, KPIs, table explorer, incidents, catalog, evals, SQL console, UI-vs-database check; API key, rate limit, audit log | FastAPI, Uvicorn, Pydantic | ✅ Done |
| 7 | React UI: Ask, Dashboard, Explorer, Incident, Catalog, Evals, Data check, served by the API at `/web/`; automated test suite (83 pytest + 22 Playwright) | React 19, TypeScript, Vite, Tailwind CSS 4, TanStack Query, Recharts, pytest | ✅ Done |

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

In Claude Code, `/build-large` does all of this in one step (seed, catalog, golden set and a
self-test); add `live` to also run the evals against the OpenAI API.

### Run the application

```bash
cp .env.example .env                # set OPENAI_API_KEY (and ANTHROPIC_API_KEY for Claude)
python run_app.py                   # API on :8000 (docs at /docs), UI on http://127.0.0.1:8000/web/
```

The React front end (needs Node.js 20+) is built once and then served by the API:

```bash
cd web && npm install && npm run build    # then open http://127.0.0.1:8000/web/
```

Ask a question from the command line instead:

```bash
python agent/nl2sql.py "which assignment groups breached SLA most last month?"
python agent/nl2sql.py --provider anthropic "how many P1 incidents are open?"
```

Tests (no API key needed; they build their own database in a temp folder):

```bash
python -B -m pytest tests -p no:cacheprovider
```

To run the Day 1 spike, which calls the OpenAI API:

```bash
cp .env.example .env                # then set OPENAI_API_KEY in .env
python agent/naive_spike.py
```

## Files you create locally (not in this repo)

Three files are deliberately **not** committed (see `.gitignore`). A fresh clone does not have
them; create them as below before running anything.

| File | What it is | Why it is not in the repo | How to create it |
|---|---|---|---|
| `.env` | Your OpenAI API key (`OPENAI_API_KEY`) and, optionally, the model (`OPENAI_MODEL`, default `gpt-4o-mini`) | It holds a secret; publishing it would let anyone use your OpenAI account | Copy the template and add your key (below) |
| `db/tickets.sqlite` | The sample ITSM database: 500 incidents, 100 changes, 40 users, plus the `meta_*` semantic catalog (about 0.2 MB) | It is generated, and identical on every build, so it can always be recreated | `python db/seed.py` then `python semantics/build_catalog.py` |
| `db/tickets_large.sqlite` | The large test database: 50,000 incidents and 10,000 changes, plus the catalog (about 11 MB) | Generated and large | The large-scale commands above |

**`.env`:**

```bash
cp .env.example .env          # Windows Command Prompt: copy .env.example .env
```

Then open `.env` and set `OPENAI_API_KEY=` to your key from
https://platform.openai.com/api-keys (the account needs API credits; a ChatGPT subscription does
not include them). The agent and the spike read `.env` from the project root. Never commit it
and never paste the key into chats or issues.

Only the OpenAI-calling parts need `.env`: `agent/nl2sql.py`, `agent/naive_spike.py` and a live
`evals/run_evals.py`. Building the databases, `run_evals.py --self-test` and the catalog work
without it.

**The databases:** everything that uses a database expects it to exist and tells you the
command if it does not. Rebuilding is always safe: `db/seed.py` recreates the file from scratch
with the same data (fixed seed 42, "today" fixed at 28 Sep 2026), and `build_catalog.py` must
be run after every seed because seeding replaces the whole file. To check a fresh setup:

```bash
python evals/run_evals.py --self-test    # expects 51/51, no API key needed
```

## Project structure

```
.
├── db/
│   ├── schema.sql            # 5-table SQLite schema: keys, constraints, indexes
│   └── seed.py               # deterministic synthetic data → db/tickets.sqlite
├── semantics/
│   └── build_catalog.py      # builds the meta_* semantic layer inside the database
├── agent/
│   ├── nl2sql.py             # the agent: catalog context → model → guarded SQL → rows → answer
│   ├── llm.py                # model providers (OpenAI, Anthropic), fallback, usage
│   └── naive_spike.py        # Day 1 spike: question → OpenAI → SQL, no context, no guardrails
├── evals/                    # golden sets, eval runner, golden-set generator
├── api/                      # FastAPI service (see api/README.md)
├── web/                      # React + TypeScript front end (see web/README.md)
├── docs/images/              # screenshots used in this README
├── End-to-End/               # complete guide: every folder, script and component, start to finish
├── tests/                    # pytest: guardrails, providers, API end to end (fake model)
├── run_app.py                # starts the API, which also serves the React UI
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

Enforced in the agent and the API: **read-only** database · **one SELECT only** ·
**at most 1,000 rows** · **5-second query timeout** · **size and memory limits** per query ·
**no system functions** (an allow-list decides what a query may do) · **no personal data**
(`users.name` blocked and masked) · questions about data that does not exist are **refused** ·
optional API key, per-client rate limits, **allow-listed models**, API keys **redacted** from
errors, browser **security headers** and an **audit log** of every question with its SQL and
model. Details in [api/README.md](api/README.md#safety); every known attack is a test in
`tests/test_security.py`.

## Tech stack

Python · SQLite (date expressions go through `db/dialect.py`, with a PostgreSQL variant
not yet run against a server) · OpenAI or Anthropic API at runtime ·
FastAPI + Uvicorn · React + TypeScript (Vite, Tailwind CSS,
TanStack Query, Recharts) · pytest. The per-day breakdown is in [Status](#status).
`db/` and `semantics/` use the standard library only. `httpx` is pinned to 0.27.2 because the
pinned `openai` 1.51.2 breaks on newer versions.

## How this project was built

### What the project does

IT support teams record every problem as a ticket. Managers constantly need answers from those
tickets: *which team is missing its deadlines? how long do fixes take? what risky changes are
coming up?* Normally that means asking an analyst to write a database query.

This project removes that step. You type the question in plain English, and the app:

1. looks up what your words mean in a built-in **dictionary** of the company's terms,
2. asks an **AI model** to write the database query,
3. **safety-checks** the query (read-only, no personal data) before running it,
4. replies in a sentence, with a chart and the query it used, so the answer can be checked.

It was built with **Claude Code**, an AI coding assistant, by repeatedly trying the app, finding
what went wrong, fixing the cause and re-testing everything against a set of questions with
known answers.

### The pages

**Home**: the starting point. Shows that the service is running, how much data is loaded, and
links to every page.

![Home page](docs/images/home.png)

**Ask**: the heart of the app. Type a question and get a plain-English answer, a chart, the
table of results and the query behind it. It also suggests follow-up questions, and you can
rate each answer.

![Ask page](docs/images/ask.png)

**Dashboard**: the health of the service at a glance: total and open tickets, missed deadlines
(SLA breaches), average fix time and reopen rate, with trends by month, team, priority and
status. Click a team to see its tickets.

![Dashboard page](docs/images/dashboard.png)

**Explorer**: browse every table in the database like a spreadsheet: filter, search, sort and
download. Staff names are hidden. Click a ticket to open it.

![Explorer page](docs/images/explorer.png)

**Incident**: one ticket in detail: how much of its deadline it used, a timeline of what happened
when, and similar past tickets that may help solve it.

![Incident page](docs/images/incident.png)

**Catalog**: the dictionary the AI uses: every business term ("P1", "breach", "last month") and
exactly what it means in the data. Terms that are unclear or not in the data are flagged.

![Catalog page](docs/images/catalog.png)

**Data check**: proof that the screens tell the truth. Every number the app shows is
recalculated directly from the database and compared (25 of 25 match). You can also run your
own read-only query here.

![Data check page](docs/images/data-check.png)

**Evals**: scores the AI on a set of test questions whose correct answers are
known, so any drop in accuracy is caught straight away.

![Evals page](docs/images/evals.png)

**Light and dark**: the switch in the top-right corner of every page flips the whole app; the
choice is remembered, and the first visit follows your operating system setting. The layout also
adapts to tablets and phones (the sidebar becomes a menu).

Every page has a dark version. Files in `docs/images/` use the page name plus `-dark`, for
example `dashboard-dark.png`.

![Home page in dark mode](docs/images/home-dark.png)
![Ask page in dark mode](docs/images/ask-dark.png)
![Dashboard page in dark mode](docs/images/dashboard-dark.png)
![Explorer page in dark mode](docs/images/explorer-dark.png)
![Incident page in dark mode](docs/images/incident-dark.png)
![Catalog page in dark mode](docs/images/catalog-dark.png)
![Evals page in dark mode](docs/images/evals-dark.png)
![Data check page in dark mode](docs/images/data-check-dark.png)
