# 11. Operations: set up, run, configure, maintain

## First-time setup

Needs Python 3.11+ (SQLite 3.37+ is included). Node.js 20+ only for building the React UI.

```bash
pip install -r requirements.txt
cp .env.example .env                 # then set OPENAI_API_KEY (and ANTHROPIC_API_KEY for Claude)
python db/seed.py                    # build db/tickets.sqlite
python semantics/build_catalog.py    # add the meta_* catalog (always after seeding)
cd web && npm install && npm run build && cd ..    # optional: the React UI
python -B -m pytest tests -p no:cacheprovider      # 136 tests, no API key needed
python evals/run_evals.py --self-test              # expect 80/80
cd web && npm run e2e && cd ..                     # 22 Playwright checks in Edge (starts its own API on 8010)
```

## Running

| What | Command | Open |
|---|---|---|
| Everything | `python run_app.py` | React `http://127.0.0.1:8000/web/`, API docs `http://127.0.0.1:8000/docs` |
| API only | `uvicorn api.main:app --port 8000` | `/docs`, `/web/` |
| React in development | `cd web && npm run dev` (with the API running) | `http://localhost:5173` |
| One question, no UI | `python agent/nl2sql.py "how many P1 incidents are open?"` | terminal |
| Another provider | `python agent/nl2sql.py --provider anthropic "…"` | terminal |
| Large dataset | add `--db db/tickets_large.sqlite`, or pick **large** in the UI sidebar | |
| Live evals | `python evals/run_evals.py [--provider …] [--golden evals/golden_set_large.yaml]` | terminal |

`run_app.py` options: `--api-port`, `--ui-port`, `--host` (default `127.0.0.1`; any other
address requires `APP_API_KEY`). Ctrl+C stops both servers.

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | OpenAI access (needed for live answers with OpenAI) |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model |
| `ANTHROPIC_API_KEY` | — | Anthropic access |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | Anthropic model |
| `LLM_PROVIDER` | `openai` | Default provider |
| `LLM_MODEL` | — | Model for the default provider |
| `LLM_FALLBACK_PROVIDER` | — | Tried automatically when the default fails |
| `LLM_ALLOWED_MODELS` | — | Extra models the API may be asked for (`model` or `provider:model`, comma-separated) |
| `APP_API_KEY` | — | Required `X-API-Key` on `/api/*` when set |
| `RATE_LIMIT_PER_MIN` | 30 | Per client IP, per bucket |
| `CORS_ORIGINS` | `localhost:5173` | Allowed browser origins (Vite dev server; the built UI needs none) |
| `DB_PATH`, `DB_LARGE_PATH` | `db/…` | Dataset files |
| `AUDIT_LOG` | `logs/audit.jsonl` | Audit file |
| `VITE_APP_API_KEY` | — | Build-time key for the React bundle (internal use only) |

## Claude Code commands and skill (`.claude/`)

| Command | Does |
|---|---|
| `/smoke` | Rebuilds the database and catalog, prints row counts, runs the tests, reports runnable yes/no |
| `/build-catalog` | Rebuilds the `meta_*` tables and lists anything still undocumented |
| `/run-evals` | Runs the live evals, prints accuracy and the two worst failures |
| `/build-large [N M] [live]` | Builds the large database, its catalog and golden set, then self-tests (and optionally live-tests) it |
| Skill `diagnose-eval-failure` | Explains failed evals and names the catalog entry to fix |

`CLAUDE.md` is the project memory Claude Code reads at the start of every session: decisions,
verified facts, history of fixes and open items.

## Routine maintenance

| Task | How |
|---|---|
| Change a business definition | Edit one entry in `semantics/build_catalog.py` → `/build-catalog` → `/run-evals` (whole set, twice) |
| Change the sample data | Edit `db/seed.py` → reseed → rebuild catalog → `python evals/make_golden_set.py` → self-test |
| Add an API endpoint | `api/main.py` (+ `services.py`, `schemas.py`) → test in `tests/test_api.py` → `web/src/lib/api.ts` → page |
| Add a React page | `web/src/pages/New.tsx` → route in `App.tsx` → link in `components/Layout.tsx` → `npm run build` |
| Before every push (public repo) | Tests pass; no `__pycache__`; staged diff scanned for keys and employer/client names; never commit `.env` or `*.sqlite` |

## Troubleshooting

| Problem | Fix |
|---|---|
| `tickets.sqlite not found` | `python db/seed.py && python semantics/build_catalog.py` |
| Catalog missing after reseeding | Seeding wipes it: run `build_catalog.py` again |
| `OPENAI_API_KEY is not set` | Add it to `.env` (the account needs API credit) |
| `OpenAI() got an unexpected keyword argument 'proxies'` | Keep `httpx==0.27.2` while `openai` is 1.51.2 |
| React page shows old content | Rebuild (`npm run build`) and hard-refresh (Ctrl+F5) |
| React shows old numbers | Sidebar **Refresh from database** (the UI caches for 10 seconds) |
| `Model '…' is not enabled on this server` | Add it to `LLM_ALLOWED_MODELS` |
| Evals differ from run to run | Normal in small amounts; run the whole set more than once before concluding |

## Open items

See the "Open items / next steps" section of `CLAUDE.md`: score Anthropic live, settle the
flagged ambiguities (Resolved vs Closed), Docker, user accounts, and running the PostgreSQL
dialect against a real server. The fixed "today" is now a build setting (`AS_OF=today python
semantics/build_catalog.py`), rate limits and eval jobs live in `logs/state.sqlite` (`STATE_DB`)
so several API processes share them, and CI runs on GitHub Actions.
