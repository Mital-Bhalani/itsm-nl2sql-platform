# 6. Backend API (`api/`)

A FastAPI service on port 8000. It is the **only** component that opens the database or
calls the agent; both front ends go through it. Interactive documentation is at
`http://127.0.0.1:8000/docs`.

## Files

| File | Role |
|---|---|
| `main.py` | The app: endpoints, middleware (request id, logging, security headers), API-key check, rate limits, model check, audit log, background eval jobs, React site mount |
| `services.py` | The data logic behind the non-AI endpoints; no AI involved |
| `schemas.py` | Pydantic models that validate requests and shape responses |
| `config.py` | `Settings` loaded once from the environment and `.env`; puts `agent/`, `semantics/`, `evals/` on the import path |
| `state.py` | `StateStore`: rate-limit windows and eval runs in one SQLite file (`STATE_DB`), safe across threads, workers and restarts; `question_history()` turns stored runs into per-question pass rates |

## Endpoints

Every `/api/*` endpoint takes `dataset=default|large` and needs the `X-API-Key` header when
`APP_API_KEY` is set.

| Method | Path | Does | Used by |
|---|---|---|---|
| GET | `/health` | Database files, catalog present, providers configured, "as of" date (always public) | Sidebar status, Home |
| GET | `/api/models` | Providers and default models | Model pickers |
| GET | `/api/overview` | Row counts, catalog counts, incident date range | Home |
| POST | `/api/ask` | Question → `nl2sql.ask()` → answer, SQL, rows, follow-ups (rate-limited, audited) | Ask |
| GET | `/api/kpis` | Headline KPIs, by team, by month, by priority, by status, upcoming changes by risk; optional `date_from`, `date_to`, `group_id` | Dashboard |
| GET | `/api/groups` | Teams (id, name) | Filters |
| GET | `/api/tables` | Data tables with description, row count and columns | Explorer |
| GET | `/api/tables/{name}` | One page of a table; `f_<column>=value` filters, `search`, `sort`, `desc`, `page`, `size` (≤ 200) | Explorer |
| GET | `/api/incidents/{id}` | Incident + team + SLA target, time used, breach flag, SLA due time, timeline | Incident |
| GET | `/api/incidents/{id}/similar` | Most similar incidents (shared description words, same team, same priority) | Incident |
| POST | `/api/feedback` | Thumbs up/down on an answer → audit log (rate-limited) | Ask |
| GET | `/api/catalog/{section}` | `tables`, `columns`, `joins`, `metrics` or `glossary` | Catalog |
| GET | `/api/reconcile` | 25 checks: every number the UI shows vs the same number from independent SQL | Data check |
| POST | `/api/sql` | Your own read-only SELECT through the same guardrails (rate-limited, audited) | Data check |
| POST | `/api/evals` | Start an eval run (self-test or live) in a background thread (rate-limited, max 2 at once across all workers) | Evals |
| GET | `/api/evals`, `/api/evals/{id}` | List past and running runs (persisted) / progress and results of one run | Evals |
| GET | `/api/evals/history` | For one golden set: the finished runs and, per question, runs, passes, pass rate, latest status and each failure; flakiest questions first | Evals |
| GET | `/web/…` | The built React site (`web/dist`) | Browser |
| GET | `/` | Redirects to `/web/` (or `/docs` if React is not built) | Browser |

## `services.py` function by function

| Function | What it does |
|---|---|
| `connect(db_path)` | Read-only connection (with limits) + authorizer; allowed across FastAPI's worker threads |
| `overview(conn)` | Row counts for the 5 data and 5 catalog tables, first/last incident date |
| `catalog_ready(conn)` | True when all data and `meta_*` tables exist |
| `kpis(conn, date_from, date_to, group_id)` | Builds every dashboard number from `meta_metrics` fragments with `_metric_query()`; breach count = rate × resolved |
| `groups`, `list_tables`, `table_columns` | Lookups for filters and the explorer |
| `browse(conn, table, filters, search, sort, …)` | Explorer page. Table and column names must exist in `meta_columns` (whitelist); values are bound parameters; PII columns are shown as `***` and cannot be filtered or sorted |
| `incident(conn, id)` | Detail with SLA maths and a timeline (opened → SLA due → resolved/now) |
| `similar_incidents(conn, id, limit)` | Jaccard word overlap on the description + 0.1 for the same team + 0.1 for the same priority |
| `catalog(conn, section)` | One catalog table |
| `db_info(path)` | File name, size, last modified (used by the sidebar) |
| `reconcile(conn)` | Compares what the pages show with `DIRECT_CHECKS`, SQL written independently from the schema definitions |
| `run_readonly_sql(conn, sql)` | `guard_sql` + `run_sql` for the SQL console |

## Request handling inside `main.py`

```mermaid
flowchart LR
    REQ["HTTP request"] --> MW["middleware<br/>request id, timing log,<br/>security headers, CSP on /web"]
    MW --> KEY["require_key<br/>X-API-Key (constant-time)"]
    KEY --> RL["limiter(bucket)<br/>per client IP, per minute"]
    RL --> VAL["pydantic validation<br/>(schemas.py)"]
    VAL --> EP["endpoint"]
    EP --> DB["open_dataset()<br/>read-only connection<br/>closed after the request"]
    EP --> AUD["audit()<br/>logs/audit.jsonl"]
    EP --> RESP["JSON response"]
```

- **A new database connection per request**, closed afterwards, so changes to the database
  file show up immediately without restarting.
- **Errors**: unknown table/column → 400; missing dataset → 404; AI unreachable → 503;
  rate limit → 429 with `Retry-After`; anything unexpected → 500 with a request id only
  (details in the server log, never a stack trace to the client).
- **Audit log**: every ask, SQL console query and feedback is one JSON line: time, request id,
  client, dataset, question/SQL, provider, model, status, row count, tokens, timings.
- **Eval jobs** run in a thread each and are written to the state store when created, after
  every 5 scored questions and when finished (newest 200 kept, max 2 running). A restart no
  longer loses history, and a job stuck in `running` for 30 minutes is closed as failed.
- **Conversation memory**: `/api/ask` accepts `history` (up to 5 earlier `{question, sql}`
  turns); the agent adds them to the user message so a follow-up such as "and by priority?"
  keeps the earlier subject.
- **Warm-up**: at start-up the provider SDK client is created in a background thread
  (`llm.warm_up()`), so the first real question does not pay the import and connection cost.

## Settings (`config.py` and environment)

| Variable | Default | Meaning |
|---|---|---|
| `APP_API_KEY` | *(empty)* | When set, required as `X-API-Key` on `/api/*` |
| `RATE_LIMIT_PER_MIN` | 30 | Per client IP, per bucket (ask, sql, evals, feedback) |
| `CORS_ORIGINS` | Vite dev server (`localhost:5173`) | Browser origins allowed to call the API from another port; the built React UI is same-origin and needs none |
| `DB_PATH` / `DB_LARGE_PATH` | `db/tickets.sqlite` / `db/tickets_large.sqlite` | The two datasets |
| `AUDIT_LOG` | `logs/audit.jsonl` | Audit file |
| `STATE_DB` | `logs/state.sqlite` | Shared state: rate-limit windows and eval-run history |
| `LLM_*`, `OPENAI_*`, `ANTHROPIC_*` | see chapter 5 | Model providers |

Start it with `uvicorn api.main:app --port 8000` or `python run_app.py` (same thing plus
start-up checks); the built React UI is served by this process at `/web/`.
