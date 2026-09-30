"""
Shared API state in one small SQLite file (STATE_DB, default logs/state.sqlite).

Two things used to live in process memory: the per-IP rate-limit windows and the eval jobs.
With more than one uvicorn worker each process had its own copy, so limits could be exceeded
N times over and a job started on one worker was "not found" on another; a restart also lost
every eval run. This store keeps both on disk, safe across threads and processes: WAL mode,
a busy timeout, and one short-lived connection per call.

    rate_hits(bucket, client, ts)        one row per allowed call, pruned after 60 s
    eval_jobs(id, ..., summary, results) one row per eval run; summary/results are JSON
"""

import json
import sqlite3
import threading
import time
from pathlib import Path

WINDOW_SECONDS = 60
MAX_JOBS = 200
STALE_MINUTES = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS rate_hits (
    bucket TEXT NOT NULL,
    client TEXT NOT NULL,
    ts     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_hits ON rate_hits (bucket, client, ts);
CREATE TABLE IF NOT EXISTS eval_jobs (
    id          TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    golden      TEXT NOT NULL,
    mode        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    results     TEXT NOT NULL
);
"""


class StateStore:
    def __init__(self, path):
        self.path = Path(path)
        self._init_lock = threading.Lock()
        self._ready = False

    # -- connections ----------------------------------------------------------
    def _connect(self):
        if not self._ready:
            with self._init_lock:
                if not self._ready:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(self.path, timeout=10)
                    try:
                        conn.execute("PRAGMA journal_mode = WAL")
                        conn.executescript(SCHEMA)
                        conn.commit()
                    finally:
                        conn.close()
                    self._ready = True
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    # -- rate limiting --------------------------------------------------------
    def hit(self, bucket, client, limit, now=None):
        """
        Record one call for (bucket, client) if fewer than `limit` happened in the last
        60 seconds. Returns (allowed, retry_after_seconds).
        """
        now = time.time() if now is None else now
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM rate_hits WHERE ts < ?", (now - WINDOW_SECONDS,))
            row = conn.execute("SELECT COUNT(*), MIN(ts) FROM rate_hits WHERE bucket = ? AND client = ?",
                               (bucket, client)).fetchone()
            count, oldest = row[0], row[1]
            if count >= limit:
                conn.commit()
                return False, int(WINDOW_SECONDS - (now - (oldest or now))) + 1
            conn.execute("INSERT INTO rate_hits (bucket, client, ts) VALUES (?, ?, ?)", (bucket, client, now))
            conn.commit()
            return True, 0
        finally:
            conn.close()

    def clear_rate_hits(self):
        conn = self._connect()
        try:
            conn.execute("DELETE FROM rate_hits")
            conn.commit()
        finally:
            conn.close()

    # -- eval jobs ------------------------------------------------------------
    @staticmethod
    def _split(job):
        summary = {k: v for k, v in job.items() if k != "results"}
        return summary, list(job.get("results") or [])

    def save_job(self, job):
        """Insert or replace a job (summary and results). Trims the table to MAX_JOBS."""
        summary, results = self._split(job)
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO eval_jobs (id, started_at, finished_at, status, golden, mode, summary, results) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job["id"], job["started_at"], job.get("finished_at"), job["status"], job["golden"],
                 job["mode"], json.dumps(summary, ensure_ascii=False, default=str),
                 json.dumps(results, ensure_ascii=False, default=str)))
            conn.execute(
                "DELETE FROM eval_jobs WHERE id NOT IN "
                "(SELECT id FROM eval_jobs ORDER BY started_at DESC, rowid DESC LIMIT ?)", (MAX_JOBS,))
            conn.commit()
        finally:
            conn.close()

    def _mark_stale(self, conn, now_iso):
        """A job still queued/running after STALE_MINUTES belongs to a dead process."""
        rows = conn.execute("SELECT id, started_at, summary FROM eval_jobs "
                            "WHERE status IN ('queued', 'running')").fetchall()
        for job_id, started_at, summary in rows:
            try:
                started = time.mktime(time.strptime(started_at[:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                continue
            if time.mktime(time.gmtime()) - started > STALE_MINUTES * 60:
                data = json.loads(summary)
                data.update(status="failed", finished_at=now_iso,
                            error=f"Run abandoned: no progress for {STALE_MINUTES} minutes "
                                  "(the server probably restarted while it was running).")
                conn.execute("UPDATE eval_jobs SET status = 'failed', finished_at = ?, summary = ? WHERE id = ?",
                             (now_iso, json.dumps(data, ensure_ascii=False, default=str), job_id))

    def running_count(self, now_iso):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._mark_stale(conn, now_iso)
            count = conn.execute("SELECT COUNT(*) FROM eval_jobs WHERE status IN ('queued', 'running')").fetchone()[0]
            conn.commit()
            return count
        finally:
            conn.close()

    def list_jobs(self, golden=None, mode=None, limit=None, now_iso=None):
        """Job summaries newest first (no results)."""
        conn = self._connect()
        try:
            if now_iso:
                conn.execute("BEGIN IMMEDIATE")
                self._mark_stale(conn, now_iso)
                conn.commit()
            sql, params = "SELECT summary FROM eval_jobs", []
            where = []
            if golden:
                where.append("golden = ?"); params.append(golden)
            if mode and mode != "all":
                where.append("mode = ?"); params.append(mode)
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY started_at DESC, rowid DESC"
            if limit:
                sql += " LIMIT ?"; params.append(int(limit))
            return [json.loads(r[0]) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def get_job(self, job_id):
        conn = self._connect()
        try:
            row = conn.execute("SELECT summary, results FROM eval_jobs WHERE id = ?", (job_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        job = json.loads(row[0])
        job["results"] = json.loads(row[1])
        return job

    def finished_jobs_with_results(self, golden, mode=None):
        """Finished (done/failed) jobs for one golden set, newest first, results included."""
        conn = self._connect()
        try:
            sql = "SELECT summary, results FROM eval_jobs WHERE golden = ? AND status IN ('done', 'failed')"
            params = [golden]
            if mode and mode != "all":
                sql += " AND mode = ?"; params.append(mode)
            sql += " ORDER BY started_at DESC, rowid DESC"
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        out = []
        for summary, results in rows:
            job = json.loads(summary)
            job["results"] = json.loads(results)
            out.append(job)
        return out


def question_history(jobs):
    """
    Per-question pass rates across finished jobs (newest first). Returns a list sorted by
    pass_rate ascending, then id, so the flakiest questions come first.
    """
    stats = {}
    for job in jobs:  # newest first, so the first sighting is the latest status
        for r in job.get("results") or []:
            q = stats.setdefault(r["id"], {"id": r["id"], "question": r.get("question"),
                                           "category": r.get("category"), "runs": 0, "passed": 0,
                                           "last_status": r.get("status"), "failures": []})
            q["runs"] += 1
            if r.get("status") == "pass":
                q["passed"] += 1
            else:
                q["failures"].append({"job_id": job["id"], "started_at": job.get("started_at"),
                                      "status": r.get("status"), "error": r.get("error")})
    for q in stats.values():
        q["pass_rate"] = round(q["passed"] / q["runs"], 3) if q["runs"] else None
    return sorted(stats.values(), key=lambda q: (q["pass_rate"] if q["pass_rate"] is not None else 2, q["id"]))
