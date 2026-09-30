# api/ — FastAPI backend

The HTTP service in front of the NL2SQL agent and the ticket database. The React UI talks
only to this API; other tools can too. Interactive docs: http://127.0.0.1:8000/docs.

```bash
python run_app.py                         # API on port 8000, React UI served at /web/
python -m uvicorn api.main:app --port 8000   # API only, from the project root
```

| file | purpose |
|---|---|
| `main.py` | app, endpoints, API-key check, rate limit, request ids, audit log, eval jobs |
| `state.py` | `StateStore`: one SQLite file (`STATE_DB`, default `logs/state.sqlite`, WAL) holding the rate-limit windows and every eval run, shared by all workers and kept across restarts |
| `services.py` | read-only data access: KPIs (formulas from `meta_metrics`), table explorer, incident detail, catalog |
| `schemas.py` | request and response models |
| `config.py` | settings from environment / `.env` |

## Endpoints

| method | path | what |
|---|---|---|
| GET | `/health` | datasets present, catalog built, which model providers have keys |
| GET | `/api/models` | providers and default models |
| GET | `/api/overview?dataset=` | row counts and data range |
| POST | `/api/ask` | `{question, provider?, model?, dataset?, history?}` → answer, follow-up questions, SQL, rows, assumption/refusal, tokens, timings. `history` is up to 5 earlier turns `{question, sql}` of the same conversation, so "and by priority?" is understood |
| GET | `/api/kpis?date_from=&date_to=&group_id=` | headline KPIs and breakdowns by team, month, priority, status; upcoming changes |
| GET | `/api/groups` | assignment groups |
| GET | `/api/tables`, `/api/tables/{name}?f_<col>=&search=&sort=&desc=&page=&size=` | data explorer |
| GET | `/api/incidents/{id}` | incident with SLA target, due time, resolution time, breach flag, % of target used and a timeline |
| GET | `/api/incidents/{id}/similar?limit=` | incidents with shared description words, same team or priority, ranked |
| POST | `/api/feedback` | `{request_id, rating: up|down, question?, comment?}` → recorded in the audit log |
| GET | `/api/catalog/{tables,columns,joins,metrics,glossary}` | the semantic catalog |
| GET | `/api/reconcile` | every number the UI shows next to the same number computed by separate SQL on the database, with match/differs |
| POST | `/api/sql` | `{sql, dataset?}` → run your own read-only query (same guardrails as the agent; audited, rate-limited) |
| POST / GET | `/api/evals`, `/api/evals/{id}` | start an eval run (`self-test` or `live`, any provider) and read its progress; `GET /api/evals?limit=` lists past runs newest first (they are persisted, so the list survives a restart) |
| GET | `/api/evals/history?golden=&mode=all|live|self-test&limit=` | per-question pass rate, latest status and every failure across the finished runs of one golden set, flakiest first (`runs` + `questions`) |

All `/api/*` endpoints take `dataset=default|large`.

## Safety

- Database opened **read-only**; generated and console SQL must be one `SELECT`/`WITH`, gets
  `LIMIT 1000`, never returns more than 1,000 rows (even with its own larger `LIMIT`), and is
  interrupted after 5 seconds.
- A SQLite **allow-list authorizer** permits only reading tables, calling functions and
  recursion. Pragma table functions (`pragma_database_list` revealed the server's file path),
  `ATTACH`, writes and `load_extension()` are refused.
- **Size limits** per connection: no value over 1 MB (stops `zeroblob`/`hex` memory bombs),
  SQL text up to 100 KB, no attached databases, SQLite heap capped at 512 MB.
- `users.name` is **masked** in the explorer and **blocked** by the authorizer everywhere.
- Explorer table and column names come only from the `meta_*` catalog; values are bound parameters.
- `APP_API_KEY` set → `X-API-Key` header required on `/api/*` (`/health` stays open); compared in
  constant time.
- **Rate limits** per client IP (`RATE_LIMIT_PER_MIN`, default 30), separately for `/api/ask`,
  `/api/sql`, `/api/evals` and `/api/feedback`. The client is the connecting address, so sending
  a different `X-API-Key` each time does not reset the count. The sliding windows live in the
  state store, so the limit also holds when uvicorn runs several workers.
- **Models are allow-listed**: only each provider's configured default (plus `LLM_ALLOWED_MODELS`)
  can be requested, so a caller cannot run up the bill on an expensive model. At most 2 eval
  runs at once, counted in the state store (a run still marked running after 30 minutes is
  treated as abandoned and closed as failed).
- Provider error messages have **API keys redacted** before they reach the client or the log.
- Browser **security headers** on every response (`nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`) and a strict **Content-Security-Policy** on the React UI.
- `X-Request-ID` from the caller is accepted only as a short plain token.
- Every question is appended to `logs/audit.jsonl` (gitignored): time, client, question, model,
  SQL, outcome, tokens, timings.
- Unexpected errors return a request id, never a stack trace.
- `run_app.py --host <non-local>` refuses to start without `APP_API_KEY`. The React UI has no
  login of its own: keep it local or put it behind a login proxy.
- Tests: `tests/test_security.py` (each known attack, run as a regression test).
