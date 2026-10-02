"""
Read-only data services behind the API: dashboard KPIs, the table explorer, incident detail
and the semantic catalog. No language model is involved here.

Every query uses bound parameters for values; table and column names are only ever taken
from the meta_* catalog (a whitelist), never from the request. users.name is masked and is
additionally blocked by the same SQLite authorizer the agent uses.
"""

import re
import sqlite3
from datetime import datetime, timezone

import nl2sql
from build_catalog import catalog_as_of
from dialect import DIALECT

DATA_TABLES = ("assignment_groups", "users", "sla_targets", "incidents", "changes")
CATALOG_TABLES = {"tables": "meta_tables", "columns": "meta_columns", "joins": "meta_joins",
                  "metrics": "meta_metrics", "glossary": "meta_glossary"}
MASK = "***"
MAX_PAGE_SIZE = 200


class BadRequest(ValueError):
    """The request names an unknown table/column or an invalid value (HTTP 400)."""


def connect(db_path):
    """Read-only connection with personal data blocked, usable across FastAPI's worker threads."""
    conn = nl2sql.connect_readonly(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.set_authorizer(nl2sql._authorizer)
    return conn


def _dicts(cur):
    return [dict(r) for r in cur.fetchall()]


# -----------------------------------------------------------------------------
#  Overview and health
# -----------------------------------------------------------------------------
def overview(conn):
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in DATA_TABLES}
    meta = {name: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for name, table in CATALOG_TABLES.items()}
    span = conn.execute("SELECT MIN(opened_at), MAX(opened_at) FROM incidents").fetchone()
    return {"as_of": catalog_as_of(conn), "row_counts": counts, "catalog_counts": meta,
            "incidents_from": span[0], "incidents_to": span[1]}


def catalog_ready(conn):
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return set(CATALOG_TABLES.values()) <= have and set(DATA_TABLES) <= have


# -----------------------------------------------------------------------------
#  KPIs (metric formulas come from meta_metrics, never written here)
# -----------------------------------------------------------------------------
def _metrics(conn):
    return {m["metric_name"]: m for m in _dicts(conn.execute("SELECT * FROM meta_metrics"))}


def _filters(date_from, date_to, group_id, column="i.opened_at"):
    where, params = [], []
    if date_from:
        where.append(f"{column} >= ?")
        params.append(f"{date_from} 00:00:00" if len(date_from) == 10 else date_from)
    if date_to:
        where.append(f"{column} < date(?, '+1 day')")
        params.append(date_to[:10])
    if group_id is not None:
        where.append("i.assignment_group_id = ?")
        params.append(group_id)
    return where, params


def _metric_query(metric, extra_where, group_by=None, select_group=None, extra_join=""):
    """SELECT <expr> FROM <base> <alias> <joins> WHERE <filters> AND <extra> [GROUP BY ...]."""
    cols = f"{select_group}, " if select_group else ""
    sql = (f"SELECT {cols}{metric['sql_expression']} AS value, COUNT(*) AS n "
           f"FROM {metric['base_table']} {metric['base_alias']}")
    if metric["required_joins"]:
        sql += f" {metric['required_joins']}"
    if extra_join:
        sql += f" {extra_join}"
    where = ([metric["filters"]] if metric["filters"] else []) + extra_where
    if where:
        sql += " WHERE " + " AND ".join(where)
    if group_by:
        sql += f" GROUP BY {group_by} ORDER BY {group_by}"
    return sql


def _round(value, digits=1):
    return None if value is None else round(value, digits)


def kpis(conn, date_from=None, date_to=None, group_id=None):
    metrics = _metrics(conn)
    where, params = _filters(date_from, date_to, group_id)

    def one(name):
        row = conn.execute(_metric_query(metrics[name], where), params).fetchone()
        return row["value"], row["n"]

    breach_rate, resolved = one("sla_breach_rate")
    mttr, _ = one("mttr")
    reopen_rate, total = one("reopen_rate")
    open_where = where + ["i.status IN ('New', 'In Progress', 'On Hold')"]
    open_count = conn.execute(f"SELECT COUNT(*) FROM incidents i WHERE {' AND '.join(open_where)}",
                              params).fetchone()[0]
    headline = {
        "incidents": total, "open": open_count, "resolved_or_closed": resolved,
        "sla_breaches": round((breach_rate or 0) * resolved),
        "sla_breach_rate_pct": _round(100 * breach_rate) if breach_rate is not None else None,
        "mttr_minutes": _round(mttr), "mttr_hours": _round(mttr / 60 if mttr else None),
        "reopen_rate_pct": _round(100 * reopen_rate) if reopen_rate is not None else None,
    }

    team_join = "JOIN assignment_groups g ON g.id = i.assignment_group_id"
    by_team = {}
    for name in ("sla_breach_rate", "mttr", "reopen_rate"):
        for r in conn.execute(_metric_query(metrics[name], where, "g.name", "g.name AS team",
                                            team_join), params):
            entry = by_team.setdefault(r["team"], {"team": r["team"]})
            if name == "sla_breach_rate":
                entry.update(resolved=r["n"], sla_breaches=round(r["value"] * r["n"]),
                             sla_breach_rate_pct=_round(100 * r["value"]))
            elif name == "mttr":
                entry["mttr_hours"] = _round(r["value"] / 60 if r["value"] else None)
            else:
                entry.update(incidents=r["n"], reopen_rate_pct=_round(100 * r["value"]))
    open_by_team = dict(conn.execute(
        "SELECT g.name, COUNT(*) FROM incidents i JOIN assignment_groups g "
        f"ON g.id = i.assignment_group_id WHERE {' AND '.join(open_where)} GROUP BY g.name",
        params).fetchall())
    for team, entry in by_team.items():
        entry["open"] = open_by_team.get(team, 0)

    month = "strftime('%Y-%m', i.opened_at)"
    by_month = {}
    for name in ("sla_breach_rate", "mttr", "reopen_rate"):
        for r in conn.execute(_metric_query(metrics[name], where, month, f"{month} AS month"), params):
            entry = by_month.setdefault(r["month"], {"month": r["month"]})
            if name == "sla_breach_rate":
                entry.update(resolved=r["n"], sla_breaches=round(r["value"] * r["n"]),
                             sla_breach_rate_pct=_round(100 * r["value"]))
            elif name == "mttr":
                entry["mttr_hours"] = _round(r["value"] / 60 if r["value"] else None)
            else:
                entry.update(incidents=r["n"], reopen_rate_pct=_round(100 * r["value"]))

    by_priority = []
    for r in conn.execute(_metric_query(metrics["sla_breach_rate"], where, "i.priority",
                                        "i.priority AS priority"), params):
        by_priority.append({"priority": f"P{r['priority']}", "resolved": r["n"],
                            "sla_breaches": round(r["value"] * r["n"]),
                            "sla_breach_rate_pct": _round(100 * r["value"])})
    counts = dict(conn.execute("SELECT i.priority, COUNT(*) FROM incidents i "
                               f"{'WHERE ' + ' AND '.join(where) if where else ''} "
                               "GROUP BY i.priority", params).fetchall())
    for entry in by_priority:
        entry["incidents"] = counts.get(int(entry["priority"][1:]), 0)

    by_status = _dicts(conn.execute(
        "SELECT i.status, COUNT(*) AS incidents FROM incidents i "
        f"{'WHERE ' + ' AND '.join(where) if where else ''} GROUP BY i.status ORDER BY 2 DESC",
        params))

    as_of = catalog_as_of(conn)
    change_params = [as_of]
    change_where = "c.planned_start >= ?"
    if group_id is not None:
        change_where += " AND c.assignment_group_id = ?"
        change_params.append(group_id)
    upcoming = _dicts(conn.execute(
        f"SELECT c.risk, COUNT(*) AS changes FROM changes c WHERE {change_where} "
        "AND c.status NOT IN ('Closed', 'Cancelled') GROUP BY c.risk "
        "ORDER BY CASE c.risk WHEN 'High' THEN 1 WHEN 'Moderate' THEN 2 ELSE 3 END", change_params))

    return {"as_of": as_of, "filters": {"date_from": date_from, "date_to": date_to,
                                        "group_id": group_id},
            "headline": headline, "by_team": sorted(by_team.values(), key=lambda e: e["team"]),
            "by_month": sorted(by_month.values(), key=lambda e: e["month"]),
            "by_priority": by_priority, "by_status": by_status, "upcoming_changes_by_risk": upcoming}


def groups(conn):
    return _dicts(conn.execute("SELECT id, name FROM assignment_groups ORDER BY name"))


# -----------------------------------------------------------------------------
#  Table explorer
# -----------------------------------------------------------------------------
def table_columns(conn, table):
    if table not in DATA_TABLES:
        raise BadRequest(f"Unknown table '{table}'. Choose one of: {', '.join(DATA_TABLES)}")
    return _dicts(conn.execute(
        "SELECT column_name, data_type, allowed_values, description, is_pii FROM meta_columns "
        "WHERE table_name = ? ORDER BY rowid", (table,)))


def list_tables(conn):
    out = []
    for t in _dicts(conn.execute("SELECT table_name, description, grain FROM meta_tables "
                                 "ORDER BY table_name")):
        if t["table_name"] in DATA_TABLES:
            t["rows"] = conn.execute(f"SELECT COUNT(*) FROM {t['table_name']}").fetchone()[0]
            t["columns"] = table_columns(conn, t["table_name"])
            out.append(t)
    return out


def browse(conn, table, filters=None, search=None, sort=None, descending=False, page=1, size=50):
    """One page of a data table. filters = {column: exact value}; search = text in any text column."""
    columns = table_columns(conn, table)
    names = [c["column_name"] for c in columns]
    pii = {c["column_name"] for c in columns if c["is_pii"]}
    if not 1 <= size <= MAX_PAGE_SIZE:
        raise BadRequest(f"size must be between 1 and {MAX_PAGE_SIZE}")
    if page < 1:
        raise BadRequest("page must be 1 or more")

    select = [f"'{MASK}' AS {n}" if n in pii else f"t.{n}" for n in names]
    join = ""
    if "assignment_group_id" in names:
        select.append("g.name AS assignment_group")
        join = " LEFT JOIN assignment_groups g ON g.id = t.assignment_group_id"

    where, params = [], []
    for col, value in (filters or {}).items():
        if col not in names:
            raise BadRequest(f"Unknown column '{col}' for {table}")
        if col in pii:
            raise BadRequest(f"Column '{col}' is personal data and cannot be filtered")
        where.append(f"t.{col} = ?")
        params.append(value)
    if search:
        text_cols = [c["column_name"] for c in columns
                     if c["data_type"] == "TEXT" and c["column_name"] not in pii]
        if text_cols:
            where.append("(" + " OR ".join(f"t.{c} LIKE ?" for c in text_cols) + ")")
            params += [f"%{search}%"] * len(text_cols)
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""

    order = "t.rowid"
    if sort:
        if sort not in names:
            raise BadRequest(f"Unknown sort column '{sort}' for {table}")
        if sort in pii:
            raise BadRequest(f"Column '{sort}' is personal data and cannot be sorted")
        order = f"t.{sort}"
    order += " DESC" if descending else " ASC"

    total = conn.execute(f"SELECT COUNT(*) FROM {table} t{where_sql}", params).fetchone()[0]
    rows = _dicts(conn.execute(
        f"SELECT {', '.join(select)} FROM {table} t{join}{where_sql} ORDER BY {order} "
        "LIMIT ? OFFSET ?", params + [size, (page - 1) * size]))
    return {"table": table, "columns": list(rows[0].keys()) if rows else names, "rows": rows,
            "total": total, "page": page, "size": size, "pages": max(1, -(-total // size))}


def incident(conn, incident_id):
    row = conn.execute(
        "SELECT i.*, g.name AS assignment_group, s.target_minutes, "
        "s.response_minutes AS response_target_minutes, "
        f"{DIALECT.minutes_between('i.resolved_at', 'i.opened_at')} AS resolution_minutes, "
        f"{DIALECT.minutes_between('i.responded_at', 'i.opened_at')} AS response_minutes, "
        "datetime(i.opened_at, '+' || s.target_minutes || ' minutes') AS sla_due_at, "
        "a.role AS assignee_role, k.role AS caller_role "
        "FROM incidents i JOIN assignment_groups g ON g.id = i.assignment_group_id "
        "JOIN sla_targets s ON s.priority = i.priority "
        "LEFT JOIN users a ON a.id = i.assignee_id LEFT JOIN users k ON k.id = i.caller_id "
        "WHERE i.id = ?", (incident_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)  # people appear as id + role only; users.name is never read
    as_of = catalog_as_of(conn)
    minutes = out["resolution_minutes"]
    out["resolution_minutes"] = _round(minutes)
    out["sla_breached"] = None if minutes is None else minutes > out["target_minutes"]
    response = out["response_minutes"]
    out["response_minutes"] = _round(response)
    out["response_breached"] = None if response is None else response > out["response_target_minutes"]
    out["caused_by_change"] = None
    if out["caused_by_change_id"] is not None:
        change = conn.execute("SELECT id, description, risk, status, planned_start FROM changes "
                              "WHERE id = ?", (out["caused_by_change_id"],)).fetchone()
        out["caused_by_change"] = dict(change) if change else None
    if minutes is None and out["status"] in ("New", "In Progress", "On Hold"):
        age = conn.execute(f"SELECT {DIALECT.minutes_between('?', '?')}",
                           (f"{as_of} 00:00:00", out["opened_at"])).fetchone()[0]
        out["age_minutes"] = _round(age)
        out["past_target"] = age > out["target_minutes"]
    elapsed = minutes if minutes is not None else out.get("age_minutes")
    out["target_used_pct"] = None if elapsed is None else _round(100 * elapsed / out["target_minutes"])
    events = [{"event": "Opened", "at": out["opened_at"]},
              {"event": "SLA due", "at": out["sla_due_at"]}]
    if out["responded_at"]:
        events.append({"event": "First response", "at": out["responded_at"]})
    if out["escalated_at"]:
        events.append({"event": "Escalated", "at": out["escalated_at"]})
    if out["resolved_at"]:
        events.append({"event": out["status"], "at": out["resolved_at"]})
    elif out["status"] in ("New", "In Progress", "On Hold"):
        events.append({"event": f"Now ({out['status']})", "at": f"{as_of} 00:00:00"})
    out["timeline"] = sorted(events, key=lambda e: e["at"])
    return out


STOPWORDS = {"the", "and", "for", "with", "not", "from", "after", "into", "unable", "issue", "error"}


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in STOPWORDS}


def similar_incidents(conn, incident_id, limit=5):
    """Incidents most like this one: shared words in the description, same team, same priority."""
    base = conn.execute("SELECT id, short_desc, priority, assignment_group_id FROM incidents "
                        "WHERE id = ?", (incident_id,)).fetchone()
    if base is None:
        return None
    words = _words(base["short_desc"])
    scored = []
    for row in conn.execute(
            "SELECT i.id, i.short_desc, i.priority, i.status, i.opened_at, i.resolved_at, "
            "i.assignment_group_id, g.name AS assignment_group FROM incidents i "
            "JOIN assignment_groups g ON g.id = i.assignment_group_id "
            "WHERE i.id != ? AND (i.assignment_group_id = ? OR i.priority = ?)",
            (incident_id, base["assignment_group_id"], base["priority"])):
        other = _words(row["short_desc"])
        overlap = len(words & other) / len(words | other) if words and other else 0.0
        if overlap == 0:
            continue
        score = (overlap + 0.1 * (row["assignment_group_id"] == base["assignment_group_id"])
                 + 0.1 * (row["priority"] == base["priority"]))
        scored.append((score, dict(row)))
    scored.sort(key=lambda pair: (-pair[0], -pair[1]["id"]))
    return [{**row, "similarity": round(score, 2)} for score, row in scored[:limit]]


# -----------------------------------------------------------------------------
#  Catalog
# -----------------------------------------------------------------------------
def catalog(conn, section):
    if section not in CATALOG_TABLES:
        raise BadRequest(f"Unknown catalog section '{section}'. Choose one of: "
                         f"{', '.join(CATALOG_TABLES)}")
    return _dicts(conn.execute(f"SELECT * FROM {CATALOG_TABLES[section]} ORDER BY rowid"))


# -----------------------------------------------------------------------------
#  Database info and reconciliation (UI numbers vs independent SQL on the database)
# -----------------------------------------------------------------------------
def db_info(path):
    stat = path.stat()
    return {"file": path.name, "size_mb": round(stat.st_size / 1_048_576, 2),
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")}


# Written independently of meta_metrics on purpose, straight from the definitions in the
# schema header, so a wrong catalog fragment or a wrong API calculation shows up as a mismatch.
BREACH = f"{DIALECT.minutes_between('i.resolved_at', 'i.opened_at')} > s.target_minutes"
RESOLVED = "i.status IN ('Resolved', 'Closed')"
OPEN = "i.status IN ('New', 'In Progress', 'On Hold')"
DIRECT_CHECKS = [
    ("Incidents", "incidents", "SELECT COUNT(*) FROM incidents"),
    ("Open incidents", "open", f"SELECT COUNT(*) FROM incidents i WHERE {OPEN}"),
    ("Resolved or closed", "resolved_or_closed", f"SELECT COUNT(*) FROM incidents i WHERE {RESOLVED}"),
    ("SLA breaches", "sla_breaches",
     f"SELECT COUNT(*) FROM incidents i JOIN sla_targets s ON s.priority = i.priority "
     f"WHERE {RESOLVED} AND {BREACH}"),
    ("SLA breach rate %", "sla_breach_rate_pct",
     f"SELECT ROUND(100.0 * SUM({BREACH}) / COUNT(*), 1) FROM incidents i "
     f"JOIN sla_targets s ON s.priority = i.priority WHERE {RESOLVED}"),
    ("MTTR minutes", "mttr_minutes",
     f"SELECT ROUND(AVG({DIALECT.minutes_between('i.resolved_at', 'i.opened_at')}), 1) "
     f"FROM incidents i WHERE {RESOLVED}"),
    ("Reopen rate %", "reopen_rate_pct",
     "SELECT ROUND(100.0 * SUM(i.reopened_count > 0) / COUNT(*), 1) FROM incidents i"),
]


def _check(name, shown, sql, actual, where):
    return {"check": name, "shown_in_ui": shown, "in_database": actual, "where_shown": where,
            "match": shown == actual, "sql": sql}


def reconcile(conn):
    """Every number the UI shows, next to the same number computed directly on the database."""
    checks = []
    counts = overview(conn)["row_counts"]
    for table, shown in counts.items():
        sql = f"SELECT COUNT(*) FROM {table}"
        checks.append(_check(f"Rows in {table}", shown, sql, conn.execute(sql).fetchone()[0], "Home"))
    for table in ("incidents", "changes"):
        sql = f"SELECT COUNT(*) FROM {table}"
        checks.append(_check(f"Explorer total for {table}", browse(conn, table, size=1)["total"], sql,
                             conn.execute(sql).fetchone()[0], "Explorer"))

    data = kpis(conn)
    for name, key, sql in DIRECT_CHECKS:
        checks.append(_check(name, data["headline"][key], sql, conn.execute(sql).fetchone()[0],
                             "Dashboard tile"))

    team_sql = ("SELECT g.name, COUNT(i.id) FROM assignment_groups g LEFT JOIN incidents i "
                "ON i.assignment_group_id = g.id LEFT JOIN sla_targets s ON s.priority = i.priority "
                f"AND {RESOLVED} AND {BREACH} WHERE s.priority IS NOT NULL GROUP BY g.name")
    direct = dict(conn.execute(team_sql).fetchall())
    for team in data["by_team"]:
        checks.append(_check(f"SLA breaches, {team['team']}", team["sla_breaches"], team_sql,
                             direct.get(team["team"], 0), "Dashboard by team"))

    status_sql = "SELECT status, COUNT(*) FROM incidents GROUP BY status"
    direct = dict(conn.execute(status_sql).fetchall())
    for row in data["by_status"]:
        checks.append(_check(f"Incidents with status {row['status']}", row["incidents"], status_sql,
                             direct.get(row["status"]), "Dashboard by status"))
    return {"checks": checks, "passed": sum(c["match"] for c in checks), "total": len(checks)}


def run_readonly_sql(conn, sql):
    """A user's own query through the same guardrails as the agent (SELECT-only, LIMIT, PII, timeout)."""
    conn.set_authorizer(None)  # run_sql installs and removes its own authorizer
    try:
        guarded = nl2sql.guard_sql(sql)
        columns, rows = nl2sql.run_sql(conn, guarded)
    except nl2sql.UnsafeSQL as exc:
        raise BadRequest(f"Blocked by guardrail: {exc}") from exc
    except sqlite3.Error as exc:
        raise BadRequest(f"SQLite error: {exc}") from exc
    finally:
        conn.set_authorizer(nl2sql._authorizer)
    return {"sql": guarded, "columns": columns, "rows": [list(r) for r in rows], "row_count": len(rows),
            "truncated": len(rows) >= nl2sql.MAX_ROWS}
