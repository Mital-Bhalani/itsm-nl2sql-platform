# api/ — FastAPI backend

The HTTP service in front of the NL2SQL agent and the ticket database. The Streamlit UI talks
only to this API; other tools can too. Interactive docs: http://127.0.0.1:8000/docs.

```bash
python run_app.py                         # API (port 8000) and UI (port 8501) together
python -m uvicorn api.main:app --port 8000   # API only, from the project root
```

| file | purpose |
|---|---|
| `main.py` | app, endpoints, API-key check, rate limit, request ids, audit log, eval jobs |
| `services.py` | read-only data access: KPIs (formulas from `meta_metrics`), table explorer, incident detail, catalog |
| `schemas.py` | request and response models |
| `config.py` | settings from environment / `.env` |

## Endpoints

| method | path | what |
|---|---|---|
| GET | `/health` | datasets present, catalog built, which model providers have keys |
| GET | `/api/models` | providers and default models |
| GET | `/api/overview?dataset=` | row counts and data range |
| POST | `/api/ask` | `{question, provider?, model?, dataset?}` → answer, follow-up questions, SQL, rows, assumption/refusal, tokens, timings |
| GET | `/api/kpis?date_from=&date_to=&group_id=` | headline KPIs and breakdowns by team, month, priority, status; upcoming changes |
| GET | `/api/groups` | assignment groups |
| GET | `/api/tables`, `/api/tables/{name}?f_<col>=&search=&sort=&desc=&page=&size=` | data explorer |
| GET | `/api/incidents/{id}` | incident with SLA target, due time, resolution time, breach flag, % of target used and a timeline |
| GET | `/api/incidents/{id}/similar?limit=` | incidents with shared description words, same team or priority, ranked |
| POST | `/api/feedback` | `{request_id, rating: up|down, question?, comment?}` → recorded in the audit log |
| GET | `/api/catalog/{tables,columns,joins,metrics,glossary}` | the semantic catalog |
| GET | `/api/reconcile` | every number the UI shows next to the same number computed by separate SQL on the database, with match/differs |
| POST | `/api/sql` | `{sql, dataset?}` → run your own read-only query (same guardrails as the agent; audited, rate-limited) |
| POST / GET | `/api/evals`, `/api/evals/{id}` | start an eval run (`self-test` or `live`, any provider) and read its progress |

All `/api/*` endpoints take `dataset=default|large`.

## Safety

- Database opened **read-only**; generated SQL must be one `SELECT`/`WITH`, gets `LIMIT 1000`,
  and is interrupted after 5 seconds.
- `users.name` is **masked** in the explorer and **blocked** by a SQLite authorizer everywhere.
- Explorer table and column names come only from the `meta_*` catalog; values are bound parameters.
- `APP_API_KEY` set → `X-API-Key` header required on `/api/*` (`/health` stays open).
- `/api/ask` is rate-limited per client (`RATE_LIMIT_PER_MIN`, default 30).
- Every question is appended to `logs/audit.jsonl` (gitignored): time, client, question, model,
  SQL, outcome, tokens, timings.
- Unexpected errors return a request id, never a stack trace.
