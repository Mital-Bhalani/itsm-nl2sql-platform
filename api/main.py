"""
HTTP API for the ITSM NL2SQL platform.

    uvicorn api.main:app --port 8000          # from the project root
    python run_app.py                          # API and UI together

Endpoints (JSON; interactive docs at /docs):
    GET  /                             redirects to the React UI (/web/) when built, else /docs
    GET  /web/                         the React front end (web/dist, built with npm run build)
    GET  /health                       database, catalog and model providers
    GET  /api/models                   providers, default models, which are configured
    GET  /api/overview                 row counts and data range for a dataset
    POST /api/ask                      question -> SQL -> rows -> plain-English answer
    GET  /api/kpis                     dashboard metrics (formulas from meta_metrics)
    GET  /api/groups                   assignment groups (for filters)
    GET  /api/tables                   data tables with columns and row counts
    GET  /api/tables/{name}            one page of a table (filter, search, sort)
    GET  /api/incidents/{id}           one incident with SLA target, breach and timeline
    GET  /api/incidents/{id}/similar   incidents with similar descriptions, team, priority
    POST /api/feedback                 thumbs up/down on an answer (goes to the audit log)
    GET  /api/catalog/{section}        tables | columns | joins | metrics | glossary
    GET  /api/reconcile                every number the UI shows vs the same number in SQL
    POST /api/sql                      run your own read-only SELECT (same guardrails)
    POST /api/evals                    start an eval run (self-test or live)
    GET  /api/evals                    past and running eval runs (kept in STATE_DB)
    GET  /api/evals/history            per-question pass rates across runs of one golden set
    GET  /api/evals/{job_id}           progress and results of an eval run

Security: read-only database with an allow-list authorizer and size limits, SELECT-only guarded
SQL capped at 1,000 rows, users.name masked/blocked, optional X-API-Key (APP_API_KEY), per-IP
rate limits on /api/ask, /api/sql, /api/evals and /api/feedback, at most MAX_RUNNING_JOBS eval
runs at once, models limited to llm.allowed_models(), provider errors with API keys redacted,
browser security headers, every question audited to logs/audit.jsonl. Rate-limit windows and
eval runs live in api/state.py (SQLite, STATE_DB), so they hold across workers and restarts.
"""

import inspect
import json
import logging
import re
import secrets
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

sys.dont_write_bytecode = True  # keep the repo free of __pycache__

from fastapi import Depends, FastAPI, HTTPException, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from api.config import ROOT, load_settings  # noqa: E402  (also puts agent/ etc. on sys.path)
from api import services  # noqa: E402
from api.state import StateStore, question_history  # noqa: E402
from api.schemas import AskRequest, AskResponse, EvalJob, EvalRunRequest, FeedbackRequest, SqlRequest  # noqa: E402

import llm  # noqa: E402
import nl2sql  # noqa: E402
import run_evals  # noqa: E402

settings = load_settings()
state = StateStore(settings.state_db)
ASK_TAKES_HISTORY = "history" in inspect.signature(nl2sql.ask).parameters
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("itsm.api")
if not settings.api_key:
    log.warning("APP_API_KEY is not set: the API accepts requests without a key (dev mode)")

app = FastAPI(title="ITSM NL2SQL API", version=settings.version,
              description="Ask ITSM ticket questions in plain English; every answer shows its SQL.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"])


def _warm_up_model_client():
    """Import the provider SDK and build its client now, so the first question is not slow."""
    warm_up = getattr(llm, "warm_up", None)
    if warm_up is None:
        return

    def run():
        try:
            warm_up()
        except Exception:  # noqa: BLE001 - warming up must never stop the API
            log.warning("model warm-up failed (the first question may be slower)", exc_info=True)

    threading.Thread(target=run, name="llm-warm-up", daemon=True).start()


@asynccontextmanager
async def _lifespan(_app):
    _warm_up_model_client()
    yield


app.router.lifespan_context = _lifespan


# -----------------------------------------------------------------------------
#  Middleware, auth, rate limit, audit
# -----------------------------------------------------------------------------
REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
# The React app loads its own scripts, Google Fonts, and inline styles (charts); nothing else.
WEB_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' "
           "https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
           "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
           "form-action 'self'; frame-ancestors 'none'")


@app.middleware("http")
async def request_context(request: Request, call_next):
    # A caller-supplied id is echoed into logs and headers, so accept only a short plain token.
    given = request.headers.get("X-Request-ID") or ""
    request_id = given if REQUEST_ID.match(given) else uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 - last-resort handler; details go to the log only
        log.exception("unhandled error request_id=%s path=%s", request_id, request.url.path)
        response = JSONResponse(status_code=500, content={
            "detail": "Internal error. Quote this request id when reporting it.",
            "request_id": request_id})
    response.headers["X-Request-ID"] = request_id
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.path.startswith("/web"):
        response.headers["Content-Security-Policy"] = WEB_CSP
    log.info("request_id=%s %s %s -> %s in %d ms", request_id, request.method, request.url.path,
             response.status_code, (time.perf_counter() - started) * 1000)
    return response


def require_key(request: Request):
    if settings.api_key:
        given = (request.headers.get("X-API-Key") or "").encode("utf-8")
        if not secrets.compare_digest(given, settings.api_key.encode("utf-8")):
            raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")


def limiter(bucket):
    """
    Per-client sliding-window limit of RATE_LIMIT_PER_MIN calls per minute for one bucket of
    endpoints. The client is the connecting IP address, never a request header, so changing
    X-API-Key or other headers does not reset the count. Windows are kept in the shared state
    store, so the limit holds across uvicorn workers.
    """
    def rate_limit(request: Request):
        client = request.client.host if request.client else "?"
        allowed, retry_after = state.hit(bucket, client, settings.rate_limit_per_min)
        if not allowed:
            raise HTTPException(status_code=429, detail=(
                f"Rate limit: {settings.rate_limit_per_min} requests per minute. Try again shortly."),
                headers={"Retry-After": str(retry_after)})
    return rate_limit


rate_limit = limiter("ask")


def check_model(provider, model):
    """Only known providers and their allowed models may be requested (stops cost abuse)."""
    if provider is not None and provider not in llm.PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")
    if model is None:
        return
    allowed = llm.allowed_models(provider or llm.default_provider())
    if model not in allowed:
        raise HTTPException(status_code=400, detail=(
            f"Model '{model}' is not enabled on this server. Allowed: {', '.join(sorted(allowed))}. "
            "An administrator can add models with LLM_ALLOWED_MODELS."))


_audit_lock = threading.Lock()


def audit(entry):
    try:
        settings.audit_log.parent.mkdir(parents=True, exist_ok=True)
        with _audit_lock, settings.audit_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        log.exception("could not write audit log %s", settings.audit_log)


def open_dataset(dataset):
    path = settings.datasets.get(dataset)
    if path is None:
        raise HTTPException(status_code=400, detail=f"Unknown dataset '{dataset}'. "
                                                    f"Choose one of: {', '.join(settings.datasets)}")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset}' has not been built "
                                                    f"({path.name} is missing).")
    return services.connect(path)


def db(dataset: str = Query("default", description="default or large")):
    conn = open_dataset(dataset)
    try:
        yield conn
    finally:
        conn.close()


@app.exception_handler(services.BadRequest)
async def bad_request(_request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# -----------------------------------------------------------------------------
#  Health and metadata
# -----------------------------------------------------------------------------
@app.get("/health", tags=["meta"])
def health():
    datasets, as_of = {}, None
    for name, path in settings.datasets.items():
        info = {"path": path.name, "exists": path.exists(), "catalog": False}
        if path.exists():
            info.update(services.db_info(path))
            try:
                conn = services.connect(path)
                info["catalog"] = services.catalog_ready(conn)
                info["as_of"] = services.catalog_as_of(conn)
                conn.close()
            except sqlite3.Error as exc:
                info["error"] = str(exc)
        datasets[name] = info
    providers = llm.available_providers()
    ok = datasets["default"]["exists"] and datasets["default"]["catalog"]
    as_of = datasets["default"].get("as_of") or next((d.get("as_of") for d in datasets.values() if d.get("as_of")), None)
    return {"status": "ok" if ok else "degraded", "version": settings.version, "as_of": as_of,
            "auth_required": bool(settings.api_key), "datasets": datasets,
            "llm_ready": any(p["configured"] for p in providers), "providers": providers}


@app.get("/api/models", tags=["meta"], dependencies=[Depends(require_key)])
def models():
    return {"providers": llm.available_providers()}


@app.get("/api/overview", tags=["data"], dependencies=[Depends(require_key)])
def overview(conn=Depends(db)):
    return services.overview(conn)


# -----------------------------------------------------------------------------
#  Ask
# -----------------------------------------------------------------------------
@app.post("/api/ask", tags=["ask"], response_model=AskResponse,
          dependencies=[Depends(require_key), Depends(rate_limit)])
def ask(body: AskRequest, request: Request):
    check_model(body.provider, body.model)
    conn = open_dataset(body.dataset)
    request_id = request.state.request_id
    entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "request_id": request_id, "client": request.client.host if request.client else None,
             "dataset": body.dataset, "question": body.question, "provider": body.provider,
             "model": body.model}
    history = [t.model_dump() for t in body.history]
    extra = {"history": history} if history and ASK_TAKES_HISTORY else {}
    if history and not ASK_TAKES_HISTORY:
        log.warning("conversation history ignored: this nl2sql.ask has no 'history' parameter")
    try:
        result = nl2sql.ask(body.question, conn, body.provider, body.model, answer=body.answer, **extra)
    except llm.AgentAPIError as exc:
        message = llm.redact(exc)
        log.warning("model error request_id=%s: %s", request_id, message)
        audit({**entry, "status": "model_error", "error": message})
        raise HTTPException(status_code=503, detail=f"The language model could not be reached: {message}")
    finally:
        conn.close()
    status = ("refused" if result["refusal"] else "blocked" if result["unsafe"]
              else "error" if result["error"] else "answered")
    audit({**entry, "status": status, "provider": result["provider"], "model": result["model"],
           "sql": result["sql"], "row_count": result["row_count"], "repaired": result["repaired"],
           "tokens_in": result["tokens_in"], "tokens_out": result["tokens_out"],
           "timings": result["timings"], "error": result["error"] or result["unsafe"]})
    return {**result, "terms": [list(t) for t in result["terms"]], "request_id": request_id}


# -----------------------------------------------------------------------------
#  Dashboard, explorer, catalog
# -----------------------------------------------------------------------------
@app.get("/api/kpis", tags=["data"], dependencies=[Depends(require_key)])
def kpis(conn=Depends(db),
         date_from: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
         date_to: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
         group_id: int | None = None):
    return services.kpis(conn, date_from, date_to, group_id)


@app.get("/api/groups", tags=["data"], dependencies=[Depends(require_key)])
def groups(conn=Depends(db)):
    return services.groups(conn)


@app.get("/api/tables", tags=["data"], dependencies=[Depends(require_key)])
def tables(conn=Depends(db)):
    return services.list_tables(conn)


@app.get("/api/tables/{name}", tags=["data"], dependencies=[Depends(require_key)])
def browse(name: str, request: Request, conn=Depends(db),
           search: str | None = Query(None, max_length=100),
           sort: str | None = None, desc: bool = False,
           page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=services.MAX_PAGE_SIZE)):
    """Filter with ?f_<column>=<value> (exact match), e.g. ?f_priority=1&f_status=New."""
    filters = {k[2:]: v for k, v in request.query_params.items() if k.startswith("f_") and v != ""}
    return services.browse(conn, name, filters, search, sort, desc, page, size)


@app.get("/api/incidents/{incident_id}", tags=["data"], dependencies=[Depends(require_key)])
def incident(incident_id: int, conn=Depends(db)):
    found = services.incident(conn, incident_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return found


@app.get("/api/incidents/{incident_id}/similar", tags=["data"], dependencies=[Depends(require_key)])
def similar(incident_id: int, conn=Depends(db), limit: int = Query(5, ge=1, le=20)):
    found = services.similar_incidents(conn, incident_id, limit)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return found


@app.post("/api/feedback", tags=["ask"], status_code=201,
          dependencies=[Depends(require_key), Depends(limiter("feedback"))])
def feedback(body: FeedbackRequest, request: Request):
    audit({"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "feedback",
           "request_id": request.state.request_id, "answer_request_id": body.request_id,
           "client": request.client.host if request.client else None, "rating": body.rating,
           "question": body.question, "comment": body.comment})
    return {"recorded": True}


@app.get("/api/catalog/{section}", tags=["catalog"], dependencies=[Depends(require_key)])
def catalog(section: str, conn=Depends(db)):
    return services.catalog(conn, section)


@app.get("/api/reconcile", tags=["data"], dependencies=[Depends(require_key)])
def reconcile(conn=Depends(db)):
    return services.reconcile(conn)


@app.post("/api/sql", tags=["data"], dependencies=[Depends(require_key), Depends(limiter("sql"))])
def run_sql(body: SqlRequest, request: Request):
    conn = open_dataset(body.dataset)
    entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "request_id": request.state.request_id, "kind": "sql_console",
             "client": request.client.host if request.client else None, "dataset": body.dataset,
             "sql": body.sql}
    try:
        result = services.run_readonly_sql(conn, body.sql)
    except services.BadRequest as exc:
        audit({**entry, "status": "rejected", "error": str(exc)})
        raise
    finally:
        conn.close()
    audit({**entry, "status": "ok", "row_count": result["row_count"]})
    return result


# -----------------------------------------------------------------------------
#  Evals (background threads; every job is persisted in the state store)
# -----------------------------------------------------------------------------
MAX_RUNNING_JOBS = 2  # live runs spend API credit and each holds a thread
SAVE_EVERY = 5        # persist progress after this many scored questions
_jobs_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_eval_job(job, questions, db_path):
    conn = None
    try:
        conn = nl2sql.connect_readonly(db_path)
        job["status"] = "running"
        state.save_job(job)
        for item in questions:
            result = run_evals.score(item, conn, job["mode"] == "self-test", job["provider"], job["model"])
            with _jobs_lock:
                job["results"].append(result)
                job["completed"] += 1
                job["passed"] += result["status"] == "pass"
                if job["completed"] % SAVE_EVERY == 0:
                    state.save_job(job)
        job["execution_accuracy"] = round(job["passed"] / job["total"], 4) if job["total"] else 0.0
        job["status"] = "done"
    except llm.AgentAPIError as exc:
        job.update(status="failed",
                   error=f"Model call failed after {job['completed']} questions: {llm.redact(exc)}")
    except Exception:  # noqa: BLE001 - report any failure on the job instead of losing it
        log.exception("eval job %s failed", job["id"])  # details stay in the server log
        job.update(status="failed", error="Internal error while running the evaluation; see the server log.")
    finally:
        job["finished_at"] = _now()
        with _jobs_lock:
            state.save_job(job)
        if conn is not None:
            conn.close()


@app.post("/api/evals", tags=["evals"], response_model=EvalJob, status_code=202,
          dependencies=[Depends(require_key), Depends(limiter("evals"))])
def start_eval(body: EvalRunRequest):
    path = settings.golden_sets.get(body.golden)
    if path is None:
        raise HTTPException(status_code=400, detail=f"Unknown golden set '{body.golden}'. "
                                                    f"Choose one of: {', '.join(settings.golden_sets)}")
    golden = run_evals.load_golden_file(path)
    db_path = ROOT / golden.get("database", "db/tickets.sqlite")
    if not db_path.exists():
        raise HTTPException(status_code=404, detail=f"{db_path.name} has not been built; run /build-large "
                                                    "or db/seed.py first.")
    provider = model = None
    if body.mode == "live":
        provider = body.provider or llm.default_provider()
        if provider not in llm.PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")
        if not any(p["name"] == provider and p["configured"] for p in llm.available_providers()):
            raise HTTPException(status_code=400, detail=f"Provider '{provider}' has no API key configured")
        check_model(provider, body.model)
        model = body.model or llm.default_model(provider)
    job = {"id": uuid.uuid4().hex[:10], "status": "queued", "mode": body.mode, "golden": body.golden,
           "provider": provider, "model": model, "total": len(golden["questions"]), "completed": 0,
           "passed": 0, "execution_accuracy": None, "error": None, "started_at": _now(),
           "finished_at": None, "results": []}
    with _jobs_lock:
        if state.running_count(_now()) >= MAX_RUNNING_JOBS:
            raise HTTPException(status_code=429, detail=(
                f"{MAX_RUNNING_JOBS} evaluations are already running. Wait for one to finish."))
        state.save_job(job)
    threading.Thread(target=_run_eval_job, args=(job, golden["questions"], db_path), daemon=True).start()
    return job


@app.get("/api/evals", tags=["evals"], dependencies=[Depends(require_key)])
def list_evals(limit: int = Query(50, ge=1, le=200)):
    """Runs newest first, without per-question results; survives restarts (state store)."""
    return state.list_jobs(limit=limit, now_iso=_now())


@app.get("/api/evals/history", tags=["evals"], dependencies=[Depends(require_key)])
def eval_history(golden: str = Query("golden_set.yaml"), limit: int = Query(20, ge=1, le=200),
                 mode: str = Query("all", pattern=r"^(all|live|self-test)$")):
    """
    What the finished runs of one golden set say about each question: how often it passed,
    its latest status and every failure (job, time, status, error). Flakiest questions first.
    """
    if golden not in settings.golden_sets:
        raise HTTPException(status_code=400, detail=f"Unknown golden set '{golden}'. "
                                                    f"Choose one of: {', '.join(settings.golden_sets)}")
    jobs = state.finished_jobs_with_results(golden, mode)
    runs = [{k: v for k, v in j.items() if k != "results"} for j in jobs[:limit]]
    return {"golden": golden, "mode": mode, "runs": runs, "questions": question_history(jobs[:limit])}


@app.get("/api/evals/{job_id}", tags=["evals"], response_model=EvalJob, dependencies=[Depends(require_key)])
def get_eval(job_id: str):
    with _jobs_lock:
        job = state.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Eval job {job_id} not found")
    return job


# -----------------------------------------------------------------------------
#  React front end (web/, built with `npm run build`) served at /web/
# -----------------------------------------------------------------------------
WEB_DIST = ROOT / "web" / "dist"
if WEB_DIST.is_dir():
    app.mount("/web", StaticFiles(directory=WEB_DIST, html=True), name="web")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/web/" if WEB_DIST.is_dir() else "/docs")
