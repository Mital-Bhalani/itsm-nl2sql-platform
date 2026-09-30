"""
Build the semantic catalog (meta_* tables) inside db/tickets.sqlite.

    python db/seed.py                  # build the data first (it recreates the file)
    python semantics/build_catalog.py
    python semantics/build_catalog.py --db db/tickets_large.sqlite   # any other database

Creates five tables:
    meta_tables    one row per data table: what it holds and its grain
    meta_columns   one row per data column: description, example, allowed values, flags
    meta_glossary  business terms ("breach", "open incident", ...) and what they mean here
    meta_metrics   named metrics with the SQL expression that computes them
    meta_joins     the valid join paths between data tables

All five tables are populated.

meta_tables: what each data table holds and what one row represents (TABLE_DRAFTS).

meta_joins: one row per foreign key in schema.sql, with cardinality and pitfalls
(JOINS). The build fails if JOINS and the schema's foreign keys disagree.

meta_columns: structure (types, nullability, keys, foreign keys, CHECK lists) is
read from db/schema.sql; descriptions, example values and synonyms are drafted by
hand below. Columns whose meaning is not settled by the schema are flagged with
is_ambiguous = 1 and a note, rather than guessed.

meta_metrics: mttr, sla_breach_rate and reopen_rate, each stored as reusable SQL
fragments (expression, joins, filters) so the agent looks them up instead of
writing the formula itself.

meta_glossary: the semantic layer. Maps the words service managers use ("P1",
"team", "missed SLA", "last month") to an entity, a value condition, a metric or
a time window. Terms the data cannot answer ("assignee", "response time") are
kept with is_answerable = 0 so the agent can say so instead of guessing.

Relative time terms are anchored to AS_OF, the fixed "today" of the sample data
(NOW in db/seed.py).
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "db"))
from dialect import DIALECT  # noqa: E402  (db/dialect.py, standard library only)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "db" / "schema.sql"
DB_PATH = ROOT / "db" / "tickets.sqlite"

META_DDL = """
DROP TABLE IF EXISTS meta_tables;
DROP TABLE IF EXISTS meta_columns;
DROP TABLE IF EXISTS meta_glossary;
DROP TABLE IF EXISTS meta_settings;
DROP TABLE IF EXISTS meta_metrics;
DROP TABLE IF EXISTS meta_joins;

-- settings the catalog was built with (as_of = the date relative time terms are anchored to)
CREATE TABLE meta_settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
) STRICT;

CREATE TABLE meta_tables (
    table_name   TEXT PRIMARY KEY,
    description  TEXT NOT NULL,
    grain        TEXT NOT NULL             -- what one row represents
) STRICT;

CREATE TABLE meta_columns (
    table_name      TEXT    NOT NULL,
    column_name     TEXT    NOT NULL,
    data_type       TEXT    NOT NULL,
    is_nullable     INTEGER NOT NULL CHECK (is_nullable IN (0, 1)),
    is_primary_key  INTEGER NOT NULL CHECK (is_primary_key IN (0, 1)),
    references_to   TEXT,                  -- 'table.column' for a foreign key
    allowed_values  TEXT,                  -- comma-separated CHECK list, if any
    description     TEXT    NOT NULL,
    example_value   TEXT,
    is_pii          INTEGER NOT NULL CHECK (is_pii IN (0, 1)),
    is_ambiguous    INTEGER NOT NULL CHECK (is_ambiguous IN (0, 1)),
    ambiguity_note  TEXT,
    synonyms        TEXT,                  -- comma-separated words users say for this column
    PRIMARY KEY (table_name, column_name),
    CHECK ((is_ambiguous = 1) = (ambiguity_note IS NOT NULL))
) STRICT;

-- Business vocabulary. sql_hint uses the standard aliases
--   i = incidents, c = changes, g = assignment_groups, u = users, s = sla_targets
-- and two placeholders the agent fills in:
--   {time_column}  the column to filter on (a metric's time_column, or i.opened_at)
--   {n}            a number taken from the question (e.g. "severity 2" -> 2)
CREATE TABLE meta_glossary (
    term             TEXT    PRIMARY KEY,
    kind             TEXT    NOT NULL
                     CHECK (kind IN ('entity', 'value', 'metric', 'time', 'concept')),
    synonyms         TEXT,                 -- comma-separated words users say for this term
    definition       TEXT    NOT NULL,
    sql_hint         TEXT,                 -- entity: FROM clause; value/time/metric: WHERE condition
    metric_name      TEXT    REFERENCES meta_metrics (metric_name),
    related_columns  TEXT,                 -- comma-separated 'table.column' list
    is_answerable    INTEGER NOT NULL CHECK (is_answerable IN (0, 1)),
    is_ambiguous     INTEGER NOT NULL CHECK (is_ambiguous IN (0, 1)),
    ambiguity_note   TEXT,
    CHECK ((is_ambiguous = 1) = (ambiguity_note IS NOT NULL)),
    CHECK (is_answerable = 1 OR sql_hint IS NULL)
) STRICT;

-- Each metric is a reusable SQL fragment. The agent composes it as:
--   SELECT [group columns,] <sql_expression> AS <metric_name>
--   FROM <base_table> <base_alias> [<required_joins>] [other joins]
--   WHERE <filters> [AND question-specific filters on <time_column> etc.]
--   [GROUP BY group columns]
CREATE TABLE meta_metrics (
    metric_name     TEXT PRIMARY KEY,
    description     TEXT NOT NULL,
    unit            TEXT NOT NULL,         -- e.g. 'minutes', 'ratio (0-1)'
    base_table      TEXT NOT NULL,
    base_alias      TEXT NOT NULL,         -- alias the fragments below refer to
    sql_expression  TEXT NOT NULL,         -- aggregate expression over base_table
    required_joins  TEXT,                  -- JOIN clauses the expression depends on
    filters         TEXT,                  -- WHERE condition the metric always applies
    time_column     TEXT NOT NULL,         -- column to filter on for "last month" etc.
    notes           TEXT
) STRICT;

CREATE TABLE meta_joins (
    left_table    TEXT NOT NULL,
    left_column   TEXT NOT NULL,
    right_table   TEXT NOT NULL,
    right_column  TEXT NOT NULL,
    cardinality   TEXT NOT NULL CHECK (cardinality IN ('many-to-one', 'one-to-one', 'one-to-many')),
    notes         TEXT,
    PRIMARY KEY (left_table, left_column, right_table, right_column)
) STRICT;
"""

# -----------------------------------------------------------------------------
#  Drafted column descriptions
#  (table, column) -> (description, example_value, is_pii, ambiguity_note or None)
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
#  Priority vocabulary: the single source for every priority description,
#  synonym and glossary term below. Update wording here only.
#  priority -> (label, SLA target in words, what users say)
#  Severity N means priority N (confirmed by the business on 2026-09-28).
# -----------------------------------------------------------------------------
PRIORITY_LEVELS = {
    1: ("Critical", "4-hour", "P1, Priority 1, Sev1, Severity 1, Critical, urgent fix"),
    2: ("High", "8-hour", "P2, Priority 2, Sev2, Severity 2, High"),
    3: ("Medium", "2-day", "P3, Priority 3, Sev3, Severity 3, Medium"),
    4: ("Low", "5-day", "P4, Priority 4, Sev4, Severity 4, Low"),
}
PRIORITY_SAYINGS = "; ".join(
    f"{n} = {sayings}" for n, (_, _, sayings) in PRIORITY_LEVELS.items())

COLUMN_DRAFTS = {
    # assignment_groups
    ("assignment_groups", "id"): (
        "Identifier of the support team.", "2", 0, None),
    ("assignment_groups", "name"): (
        "Name of the support team, unique across teams.", "Network", 0, None),

    # users
    ("users", "id"): (
        "Identifier of the person.", "7", 0, None),
    ("users", "name"): (
        "Full name of the person. Personal data: do not show in answers unless needed.",
        "Maya Rossi", 1, None),
    ("users", "role"): (
        "Job role: agent works tickets, team_lead leads a team, manager oversees "
        "several teams, admin administers the tool.", "agent", 0, None),
    ("users", "assignment_group_id"): (
        "Team the person belongs to. Empty for managers and admins who sit outside any team.",
        "1", 0,
        "A user can hold only one team here. It is not stated whether this is their only "
        "team or just their primary one, so team head-counts may be understated."),

    # sla_targets
    ("sla_targets", "priority"): (
        "Incident priority this target applies to, 1 (highest) to 4 (lowest). "
        f"Users say: {PRIORITY_SAYINGS}.", "1", 0, None),
    ("sla_targets", "target_minutes"): (
        "Maximum time allowed to resolve an incident of this priority, in wall-clock "
        "minutes from opened_at to resolved_at.", "240", 0,
        "Not stated whether this is a resolution or a first-response target (the breach "
        "rule in schema.sql treats it as resolution), nor whether time on hold or outside "
        "business hours should count. Targets have no effective dates, so a change "
        "rewrites history."),

    # incidents
    ("incidents", "id"): (
        "Identifier of the incident.", "101", 0, None),
    ("incidents", "short_desc"): (
        "One-line summary of what broke, as written when the incident was logged.",
        "VPN tunnel dropping for remote users", 0, None),
    ("incidents", "priority"): (
        "Urgency of the incident, 1 (highest) to 4 (lowest). "
        f"Users say: {PRIORITY_SAYINGS}. Joins to sla_targets for its deadline.",
        "3", 0, None),
    ("incidents", "status"): (
        "Where the incident is in its lifecycle. Open: New, In Progress, On Hold. "
        "Finished: Resolved, Closed. Dropped: Cancelled.", "Closed", 0,
        "The difference between Resolved and Closed is not defined in the schema "
        "(in the sample data Closed means resolved more than 5 days ago). Treat both as "
        "finished until the business confirms."),
    ("incidents", "assignment_group_id"): (
        "Team that owns the incident.", "2", 0,
        "Only one team is stored, with no reassignment history. It is not stated whether "
        "this is the team that first received the incident, the current owner, or the "
        "team that resolved it, which matters for breach-by-team questions."),
    ("incidents", "opened_at"): (
        "When the incident was reported, UTC, text 'YYYY-MM-DD HH:MM:SS'.",
        "2026-08-14 09:30:00", 0, None),
    ("incidents", "resolved_at"): (
        "When the incident was resolved, UTC, text 'YYYY-MM-DD HH:MM:SS'. Empty unless "
        "status is Resolved or Closed.", "2026-08-14 15:05:00", 0,
        "A reopen clears this value, so for reopened incidents it holds the latest "
        "resolution, not the first. Resolution times and breaches for reopened incidents "
        "depend on which one is meant."),
    ("incidents", "reopened_count"): (
        "How many times the incident was reopened after being resolved.", "0", 0, None),

    # changes
    ("changes", "id"): (
        "Identifier of the change.", "42", 0, None),
    ("changes", "description"): (
        "What the planned work is.", "Upgrade core switch firmware", 0, None),
    ("changes", "risk"): (
        "Assessed risk of the change: Low, Moderate or High.", "Moderate", 0,
        "The criteria behind each risk level, and who assigns it, are not defined."),
    ("changes", "status"): (
        "Where the change is in its lifecycle: Draft, Assess, Scheduled, Implement, "
        "Review, Closed, or Cancelled.", "Scheduled", 0, None),
    ("changes", "assignment_group_id"): (
        "Team responsible for carrying out the change.", "2", 0, None),
    ("changes", "planned_start"): (
        "Booked start of the change window, UTC, text 'YYYY-MM-DD HH:MM:SS'. Planned, "
        "not actual.", "2026-10-03 21:00:00", 0, None),
    ("changes", "planned_end"): (
        "Booked end of the change window, UTC, text 'YYYY-MM-DD HH:MM:SS'. Planned, "
        "not actual.", "2026-10-04 01:00:00", 0, None),
}

UNDRAFTED_NOTE = "No drafted description yet: column is new in schema.sql and needs review."

# -----------------------------------------------------------------------------
#  Column synonyms: words users say for each column
# -----------------------------------------------------------------------------
COLUMN_SYNONYMS = {
    ("assignment_groups", "name"): "team, group, queue, resolver group, support team, team name",
    ("users", "name"): "person, staff member, engineer, technician, analyst, employee",
    ("users", "role"): "job role, position",
    ("users", "assignment_group_id"): "user's team, member of",
    ("sla_targets", "target_minutes"): "SLA target, SLA deadline, resolution target, SLA time",
    ("incidents", "id"): "incident number, ticket number, ticket id",
    ("incidents", "short_desc"): "title, summary, subject, incident description",
    ("incidents", "priority"): "urgency, P-level, incident priority, severity, sev, "
                               + ", ".join(s for _, _, s in PRIORITY_LEVELS.values()),
    ("incidents", "status"): "incident state, ticket status",
    ("incidents", "assignment_group_id"): "owning team, assigned team, assigned group",
    ("incidents", "opened_at"): "created, raised, logged, reported, open date, created date",
    ("incidents", "resolved_at"): "fixed date, resolution date, resolved date",
    ("incidents", "reopened_count"): "reopens, number of reopens, times reopened",
    ("changes", "id"): "change number, CR number, RFC number",
    ("changes", "description"): "change summary, change title, what is being changed",
    ("changes", "risk"): "risk level, change risk",
    ("changes", "status"): "change state, change status",
    ("changes", "assignment_group_id"): "implementing team, change owner team",
    ("changes", "planned_start"): "scheduled start, window start, implementation date, start date",
    ("changes", "planned_end"): "scheduled end, window end, end date",
}

# -----------------------------------------------------------------------------
#  Glossary: the semantic layer
# -----------------------------------------------------------------------------
SAMPLE_AS_OF = "2026-09-28"  # the fixed "today" of the sample data; must match NOW in db/seed.py


def _as_of_setting():
    """
    The catalog's "today". Default: the sample data's fixed date. Set AS_OF=YYYY-MM-DD (or
    AS_OF=today for the real clock) when building the catalog over real data; the relative
    time hints ("last month", "overdue", ...) are written with this date, and the agent and
    the API read it back from meta_settings, so everything agrees on one date.
    """
    value = (os.getenv("AS_OF") or "").strip().lower()
    if not value:
        return SAMPLE_AS_OF
    if value == "today":
        return datetime.now(timezone.utc).date().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        sys.exit(f"AS_OF must be YYYY-MM-DD or 'today', not {value!r}")


AS_OF = _as_of_setting()


def catalog_as_of(conn):
    """The as-of date the connected database's catalog was built with (falls back to AS_OF)."""
    try:
        row = conn.execute("SELECT value FROM meta_settings WHERE key = 'as_of'").fetchone()
    except sqlite3.Error:
        row = None
    return row[0] if row else AS_OF


OPEN_STATUSES = "i.status IN ('New', 'In Progress', 'On Hold')"
RESOLVED_LATE = f"{DIALECT.minutes_between('i.resolved_at', 'i.opened_at')} > s.target_minutes"


def window(start, end):
    """
    A time-window condition on {time_column}: start and end are (base, *modifiers) tuples
    for DIALECT.date_from, e.g. (AS_OF, "start of month", "-1 month").
    """
    return (f"{{time_column}} >= {DIALECT.date_from(repr(start[0]), *start[1:])} "
            f"AND {{time_column}} < {DIALECT.date_from(repr(end[0]), *end[1:])}")


def quarter_start(offset=0):
    """First day of the calendar quarter `offset` quarters from AS_OF's quarter (ISO date).
    SQLite has no 'start of quarter' modifier (it silently returns NULL), so the quarter
    windows below are written as literal dates computed here."""
    today = date.fromisoformat(AS_OF)
    index = today.year * 4 + (today.month - 1) // 3 + offset
    return date(index // 4, index % 4 * 3 + 1, 1).isoformat()


def term(term, kind, synonyms, definition, sql_hint=None, metric_name=None,
         related_columns=None, answerable=True, ambiguity=None):
    return {
        "term": term, "kind": kind, "synonyms": synonyms, "definition": definition,
        "sql_hint": sql_hint, "metric_name": metric_name, "related_columns": related_columns,
        "is_answerable": 1 if answerable else 0,
        "is_ambiguous": 1 if ambiguity else 0, "ambiguity_note": ambiguity,
    }


GLOSSARY = [
    # --- entities ------------------------------------------------------------
    term("incident", "entity", "ticket, issue, incident ticket, fault",
         "Something that broke and needed fixing. 'Ticket' on its own means an incident.",
         "incidents i"),
    term("change", "entity", "change request, CR, RFC, planned change, change ticket",
         "Planned work on IT systems with a booked time window.",
         "changes c"),
    term("assignment group", "entity", "team, group, queue, resolver group, support team",
         "A support team. Incidents and changes join to it on assignment_group_id.",
         "assignment_groups g", related_columns="assignment_groups.name"),
    term("user", "entity", "person, staff, engineer, technician, analyst, employee",
         "A person in the IT organisation. Names are personal data.",
         "users u", related_columns="users.name, users.role"),
    term("SLA target", "entity", "SLA, SLA deadline, resolution target",
         "The time allowed to resolve an incident, per priority. "
         "Join: sla_targets s ON s.priority = i.priority.",
         "sla_targets s", related_columns="sla_targets.target_minutes"),

    # --- incident priority ---------------------------------------------------
    *[term(f"{label.lower()} priority", "value", sayings,
           f"Priority {n} ({label}), {target} resolution target.",
           f"i.priority = {n}", related_columns="incidents.priority")
      for n, (label, target, sayings) in PRIORITY_LEVELS.items()],
    term("severity", "value", "sev",
         "Same as incident priority: severity N means priority N (confirmed by the "
         "business on 2026-09-28). There is no separate severity column.",
         "i.priority = {n}", related_columns="incidents.priority"),

    # --- incident status -----------------------------------------------------
    term("open incident", "value", "open, active, outstanding, unresolved, backlog, in flight",
         "An incident not yet resolved: always all three statuses New, In Progress and On Hold "
         "(never leave On Hold out). Cancelled is not open.",
         OPEN_STATUSES, related_columns="incidents.status"),
    term("on hold", "value", "paused, waiting, on hold",
         "An open incident that is paused, for example waiting on the user or a supplier.",
         "i.status = 'On Hold'", related_columns="incidents.status"),
    term("resolved incident", "value", "resolved, fixed, done, completed, finished",
         "An incident that has been fixed: status Resolved or Closed. 'Resolved <time window>' "
         "(e.g. resolved last week) filters the window on i.resolved_at, not opened_at.",
         "i.status IN ('Resolved', 'Closed')",
         related_columns="incidents.status, incidents.resolved_at"),
    term("closed", "value", "closed incident, closed ticket",
         "Defaults to finished (Resolved or Closed), the same as resolved incident.",
         "i.status IN ('Resolved', 'Closed')", related_columns="incidents.status",
         ambiguity="Could mean status = 'Closed' only, or any finished incident. The "
                   "difference between Resolved and Closed is not defined (see "
                   "meta_columns incidents.status). Ask when the distinction matters."),
    term("cancelled incident", "value", "cancelled, canceled, withdrawn",
         "An incident that was dropped without a fix.",
         "i.status = 'Cancelled'", related_columns="incidents.status"),
    term("reopened incident", "value", "reopened, bounced back, came back, re-opened",
         "An incident reopened at least once after being resolved.",
         "i.reopened_count > 0", related_columns="incidents.reopened_count"),
    term("overdue", "value", "past due, aging, breaching now, over target",
         "An open incident that has already been open longer than its SLA target "
         f"as of {AS_OF}. Needs the sla_targets join. Not part of sla_breach_rate.",
         f"{OPEN_STATUSES} AND {DIALECT.minutes_between(repr(AS_OF), 'i.opened_at')} "
         "> s.target_minutes",
         related_columns="incidents.status, incidents.opened_at, sla_targets.target_minutes",
         ambiguity="Some users say 'overdue' when they mean breached (resolved late). This "
                   "hint is open-and-past-target; use the SLA breach term for resolved late."),

    # --- change values -------------------------------------------------------
    term("high-risk change", "value", "high risk, risky change, high-risk",
         "A change assessed as High risk.",
         "c.risk = 'High'", related_columns="changes.risk"),
    term("moderate-risk change", "value", "moderate risk, medium risk",
         "A change assessed as Moderate risk.",
         "c.risk = 'Moderate'", related_columns="changes.risk"),
    term("low-risk change", "value", "low risk, minor change",
         "A change assessed as Low risk.",
         "c.risk = 'Low'", related_columns="changes.risk"),
    term("scheduled for", "value", "scheduled in, planned for, planned in, booked for, due in",
         "A change is scheduled for a time window when its planned_start falls in that window "
         "and it is not cancelled. The window filters c.planned_start; do not filter on "
         "c.status = 'Scheduled' (a change in Assess or Draft with a booked window still counts).",
         "c.status <> 'Cancelled'", related_columns="changes.planned_start, changes.status"),
    term("upcoming change", "value", "upcoming, future change, planned changes, next changes",
         f"A change whose window starts on or after {AS_OF} and is not cancelled.",
         f"c.planned_start >= '{AS_OF}' AND c.status <> 'Cancelled'",
         related_columns="changes.planned_start, changes.status"),
    term("cancelled change", "value", "cancelled change, withdrawn change",
         "A change that was cancelled.",
         "c.status = 'Cancelled'", related_columns="changes.status"),

    # --- user roles ----------------------------------------------------------
    term("agent", "value", "support agent, analyst role",
         "A user who works tickets.",
         "u.role = 'agent'", related_columns="users.role"),
    term("team lead", "value", "team leader, lead",
         "A user who leads one assignment group.",
         "u.role = 'team_lead'", related_columns="users.role"),
    term("manager", "value", "service manager, IT manager",
         "A user who oversees several teams; has no assignment group.",
         "u.role = 'manager'", related_columns="users.role"),

    # --- metrics -------------------------------------------------------------
    term("SLA breach", "metric", "breach, breached, missed SLA, SLA miss, out of SLA, "
                                 "late, resolved late",
         "A resolved or closed incident that took longer than its SLA target. Rate: "
         "sla_breach_rate. Count: SUM of the condition in sql_hint. Time windows such as "
         "'last month' filter on i.opened_at (the metric's time_column), not on resolved_at.",
         f"i.status IN ('Resolved', 'Closed') AND {RESOLVED_LATE}",
         metric_name="sla_breach_rate",
         related_columns="incidents.opened_at, incidents.resolved_at, sla_targets.target_minutes"),
    term("MTTR", "metric", "mean time to resolve, average resolution time, average fix time, "
                           "time to fix, resolution time",
         "Average wall-clock minutes from opened to resolved. Use metric mttr.",
         metric_name="mttr", related_columns="incidents.opened_at, incidents.resolved_at"),
    term("reopen rate", "metric", "bounce rate, re-open rate, reopen percentage",
         "Share of incidents reopened at least once. Use metric reopen_rate.",
         metric_name="reopen_rate", related_columns="incidents.reopened_count"),
    term("SLA compliance", "value", "SLA compliance rate, compliance rate, SLA attainment, "
                                    "SLA adherence, SLA success rate, SLA met rate",
         "A finished incident that met its SLA target: the opposite of an SLA breach. The "
         "compliance rate is 1 - sla_breach_rate, never the breach rate itself: report "
         "ROUND(100.0 * AVG(CASE WHEN resolution minutes <= s.target_minutes THEN 1.0 ELSE 0.0 "
         "END), 1) over finished incidents (85.0 means 85%). A count of compliant incidents is "
         "the SUM of the same condition.",
         f"i.status IN ('Resolved', 'Closed') AND NOT ({RESOLVED_LATE})",
         related_columns="incidents.status, incidents.resolved_at, sla_targets.target_minutes"),

    # --- time windows (on {time_column}, anchored to AS_OF) ------------------
    term("as-of date", "concept", "today, now, current date",
         f"The sample data is frozen at {AS_OF} 00:00 UTC. All relative dates "
         "('last month', 'this week') count from this date, not the real clock."),
    term("last month", "time", "previous month, prior month",
         "The previous calendar month.",
         window((AS_OF, "start of month", "-1 month"), (AS_OF, "start of month"))),
    term("this month", "time", "month to date, MTD, current month",
         "The current calendar month up to the as-of date.",
         window((AS_OF, "start of month"), (AS_OF, "start of month", "+1 month"))),
    term("last week", "time", "previous week, prior week",
         "The previous Monday-to-Sunday week.",
         window((AS_OF, "-6 days", "weekday 1", "-7 days"), (AS_OF, "-6 days", "weekday 1"))),
    term("next week", "time", "coming week, following week",
         "The next Monday-to-Sunday week after the current one.",
         window((AS_OF, "-6 days", "weekday 1", "+7 days"), (AS_OF, "-6 days", "weekday 1", "+14 days")),
         ambiguity=f"{AS_OF} is a Monday, so 'next week' could mean this week "
                   "(the next 7 days) or the following calendar week. The hint uses the "
                   "following calendar week."),
    term("last 30 days", "time", "past 30 days, past month, recent",
         "The 30 days before the as-of date.",
         window((AS_OF, "-30 days"), (AS_OF,))),
    term("this year", "time", "year to date, YTD, current year",
         "The current calendar year up to the as-of date.",
         window((AS_OF, "start of year"), (AS_OF, "start of year", "+1 year"))),
    term("last quarter", "time", "previous quarter, prior quarter",
         "The previous calendar quarter (Jan-Mar, Apr-Jun, Jul-Sep, Oct-Dec). SQLite has no "
         "'start of quarter' modifier: use the literal dates in the hint.",
         window((quarter_start(-1),), (quarter_start(0),))),
    term("this quarter", "time", "current quarter, quarter to date, QTD",
         "The current calendar quarter up to the as-of date. SQLite has no 'start of quarter' "
         "modifier: use the literal dates in the hint.",
         window((quarter_start(0),), (quarter_start(1),))),

    term("median", "concept", "middle value, 50th percentile, p50",
         "The middle value of the sorted list, not the average. SQLite has no MEDIAN(): put the "
         "values in a CTE v(x) with the question's filters, then SELECT AVG(x) FROM (SELECT x FROM v "
         "ORDER BY x LIMIT 2 - (SELECT COUNT(*) FROM v) % 2 OFFSET (SELECT (COUNT(*) - 1) / 2 "
         "FROM v)). Never take AVG of the raw values and call it the median."),
    term("running total", "concept", "cumulative total, cumulative count, cumulative sum, "
                                     "rolling total",
         "A cumulative sum in date order. Count per period in a subquery (for example per month "
         "with strftime('%Y-%m', i.opened_at)), then SUM(n) OVER (ORDER BY period) AS "
         "running_total in the outer query. The plain per-period counts are not a running total."),

    # --- not answerable from this data ---------------------------------------
    # "assigned to" is deliberately NOT a synonym: "incidents assigned to Network" is a team
    # question (answerable). Only wording about a person triggers the refusal.
    term("assignee", "concept", "assigned person, assigned engineer, owner, who fixed, "
                                "who resolved, who is working on, engineer on the ticket",
         "The person working an incident. Not stored: incidents link to a team, not a "
         "person. Answer at team level instead.", answerable=False),
    term("caller", "concept", "requester, reported by, raised by, customer",
         "The person who reported an incident. Not stored.", answerable=False),
    term("response time", "concept", "time to respond, first response, time to acknowledge",
         "Time until someone first responded. Not stored; only resolution time exists.",
         answerable=False),
    term("downtime", "concept", "outage duration, service down time",
         "How long a service was unavailable. Not stored; resolution time is not downtime.",
         answerable=False),
    term("impact", "concept", "business impact, users affected",
         "How many users or how much business an incident affected. Not stored.",
         answerable=False,
         ambiguity="Sometimes used as a synonym for priority. Do not map it to priority "
                   "without confirmation."),
    term("actual change window", "concept", "actual start, actual end, overran, ran over, "
                                            "change overrun",
         "When a change really ran. Only planned_start and planned_end are stored.",
         answerable=False),
    term("change-caused incident", "concept", "caused by change, change-related incident",
         "An incident caused by a change. Incidents and changes are not linked.",
         answerable=False),
    term("escalation", "concept", "escalated, escalate, escalations, escalated incident, "
                                  "escalation level",
         "Whether or when an incident was escalated. Not stored: there is no escalation "
         "column or status.", answerable=False),
    term("forecast", "concept", "predict, prediction, predicted, forecasting, projection, "
                                "projected",
         "A prediction of future ticket volume. The data holds past incidents and planned "
         "changes only; the platform does not forecast.", answerable=False),
    term("agent activity", "concept", "agent resolved, agent handled, agent closed, "
                                      "resolved by each agent, resolved by agent, "
                                      "resolved by an agent, handled by each agent, "
                                      "handled by agent, agent performance, top agent, "
                                      "best agent",
         "What an individual agent resolved or handled. Not stored: incidents link to a team, "
         "not to a person, and joining them through the team would only multiply rows. "
         "Answer at team level instead.", answerable=False),
]
# -----------------------------------------------------------------------------
#  Table descriptions: table -> (description, grain)
# -----------------------------------------------------------------------------
TABLE_DRAFTS = {
    "assignment_groups": (
        "Support teams that own incidents and changes (Service Desk, Network, Database, "
        "Application Support, Infrastructure). Join here to report anything 'by team'.",
        "one row per team"),
    "users": (
        "People in the IT organisation with their role and team. Names are personal data: "
        "never return users.name in answers. Incidents do not link to users.",
        "one row per person"),
    "sla_targets": (
        "Resolution deadline in minutes for each incident priority (1 = Critical 240, "
        "2 = High 480, 3 = Medium 2880, 4 = Low 7200).",
        "one row per priority"),
    "incidents": (
        "Unplanned interruptions: what broke, its priority, status, owning team, when it was "
        "opened and resolved, and how often it was reopened. SLA breach is derived by joining "
        "sla_targets, not stored. Totals and breakdowns by priority, status or date read this "
        "table alone (FROM incidents i, no other join); join assignment_groups only when the "
        "answer is per team or names a team.",
        "one row per incident"),
    "changes": (
        "Planned work on IT systems with risk level, status, owning team and a booked "
        "(planned, not actual) time window. Not linked to incidents.",
        "one row per change request"),
}

# -----------------------------------------------------------------------------
#  Join paths: one per foreign key in schema.sql
#  (left_table, left_column, right_table, right_column, cardinality, notes)
# -----------------------------------------------------------------------------
JOINS = [
    ("incidents", "assignment_group_id", "assignment_groups", "id", "many-to-one",
     "Team that owns the incident. Only join teams when the question asks for a result per "
     "team or names a team; a single total needs no join. For per-team results, LEFT JOIN from "
     "assignment_groups to keep teams with zero incidents, and put every condition on incidents "
     "(status, dates, priority) and any further join such as sla_targets inside that LEFT JOIN "
     "(its ON clause or a subquery). A WHERE on i.* or an INNER JOIN after it silently drops "
     "the zero-count teams. Count incidents with COUNT(i.id), never COUNT(*): after a LEFT "
     "JOIN, COUNT(*) counts the team row itself and returns 1 instead of 0."),
    ("incidents", "priority", "sla_targets", "priority", "many-to-one",
     "Required for SLA breach: compare resolution minutes with s.target_minutes."),
    ("changes", "assignment_group_id", "assignment_groups", "id", "many-to-one",
     "Team that carries out the change."),
    ("users", "assignment_group_id", "assignment_groups", "id", "many-to-one",
     "Team membership; NULL for managers and admins (use LEFT JOIN to keep them). Never join "
     "users to incidents through the team: it multiplies every incident by the team's head "
     "count and inflates counts."),
]


def check_tables_and_joins(columns):
    """Fail loudly when table descriptions or join paths drift from schema.sql."""
    tables = {c["table"] for c in columns}
    problems = [f"no description for table {t}" for t in sorted(tables - set(TABLE_DRAFTS))]
    problems += [f"description for unknown table {t}" for t in sorted(set(TABLE_DRAFTS) - tables)]
    schema_fks = {(c["table"], c["column"], *c["references_to"].split("."))
                  for c in columns if c["references_to"]}
    drafted = {j[:4] for j in JOINS}
    problems += [f"foreign key without a meta_joins row: {fk}" for fk in sorted(schema_fks - drafted)]
    problems += [f"meta_joins row with no foreign key: {j}" for j in sorted(drafted - schema_fks)]
    if problems:
        sys.exit("Table/join problems:\n  " + "\n  ".join(problems))


GLOSSARY_FIELDS = ["term", "kind", "synonyms", "definition", "sql_hint", "metric_name",
                   "related_columns", "is_answerable", "is_ambiguous", "ambiguity_note"]

# -----------------------------------------------------------------------------
#  Metric definitions (reusable SQL fragments, base alias i = incidents)
# -----------------------------------------------------------------------------
RESOLUTION_MINUTES = DIALECT.minutes_between("i.resolved_at", "i.opened_at")
FINISHED = "i.status IN ('Resolved', 'Closed')"

METRICS = [
    {
        "metric_name": "mttr",
        "description": "Mean time to resolve: average wall-clock minutes from opened_at "
                       "to resolved_at over resolved or closed incidents.",
        "unit": "minutes",
        "base_table": "incidents",
        "base_alias": "i",
        "sql_expression": f"AVG({RESOLUTION_MINUTES})",
        "required_joins": None,
        "filters": FINISHED,
        "time_column": "i.opened_at",
        "notes": "Clock runs 24/7, no pause for On Hold. For reopened incidents "
                 "resolved_at is the latest resolution. Divide by 60 for hours.",
    },
    {
        "metric_name": "sla_breach_rate",
        "description": "Share of resolved or closed incidents whose resolution time "
                       "exceeded the target_minutes for their priority.",
        "unit": "ratio (0-1)",
        "base_table": "incidents",
        "base_alias": "i",
        "sql_expression": f"AVG(CASE WHEN {RESOLUTION_MINUTES} > s.target_minutes "
                          "THEN 1.0 ELSE 0.0 END)",
        "required_joins": "JOIN sla_targets s ON s.priority = i.priority",
        "filters": FINISHED,
        "time_column": "i.opened_at",
        "notes": "Open incidents already past target are not counted. For a count of "
                 "breaches use SUM instead of AVG. Rate or percentage questions: report "
                 "ROUND(100.0 * <sql_expression>, 1) as a percentage. 'How many' or 'most "
                 "breaches' questions: report the count SUM(CASE WHEN ... THEN 1 ELSE 0 END), "
                 "never multiplied by 100.",
    },
    {
        "metric_name": "reopen_rate",
        "description": "Share of incidents that were reopened at least once "
                       "(reopened_count > 0).",
        "unit": "ratio (0-1)",
        "base_table": "incidents",
        "base_alias": "i",
        "sql_expression": "AVG(CASE WHEN i.reopened_count > 0 THEN 1.0 ELSE 0.0 END)",
        "required_joins": None,
        "filters": None,
        "time_column": "i.opened_at",
        "notes": "Denominator is all incidents, including open and cancelled ones that "
                 "cannot have been reopened yet. Rate or percentage questions: report "
                 "ROUND(100.0 * <sql_expression>, 1) as a percentage. 'How many reopened' "
                 "questions: report the count SUM(CASE WHEN i.reopened_count > 0 THEN 1 ELSE 0 "
                 "END), never multiplied by 100.",
    },
]
METRIC_FIELDS = ["metric_name", "description", "unit", "base_table", "base_alias",
                 "sql_expression", "required_joins", "filters", "time_column", "notes"]


def compose_metric_sql(metric):
    """The whole-table query for one metric, built only from its catalog fragments."""
    sql = (f"SELECT {metric['sql_expression']} AS {metric['metric_name']} "
           f"FROM {metric['base_table']} {metric['base_alias']}")
    if metric["required_joins"]:
        sql += f" {metric['required_joins']}"
    if metric["filters"]:
        sql += f" WHERE {metric['filters']}"
    return sql


# -----------------------------------------------------------------------------
#  Read the structure of the data tables from schema.sql
# -----------------------------------------------------------------------------
def read_schema():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    mem = sqlite3.connect(":memory:")
    mem.executescript(schema_sql)

    # CHECK (col IN ('a', 'b', ...)) lists, keyed by column name within each CREATE TABLE.
    # Keep the first match per column: that is the column's own CHECK. Later table-level
    # CHECKs (e.g. status IN ('Resolved', 'Closed') in the resolved_at rule) are subsets.
    allowed = {}
    for table, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\) STRICT;", schema_sql, re.S):
        for column, values in re.findall(r"(\w+)\s+IN\s*\(([^)]*)\)", body):
            allowed.setdefault(
                (table, column), ", ".join(v.strip().strip("'") for v in values.split(",")))

    columns = []
    tables = [r[0] for r in mem.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    for table in tables:
        fks = {r[3]: f"{r[2]}.{r[4]}" for r in mem.execute(f"PRAGMA foreign_key_list({table})")}
        for _, column, data_type, not_null, _, pk in mem.execute(f"PRAGMA table_info({table})"):
            columns.append({
                "table": table,
                "column": column,
                "data_type": data_type,
                "is_nullable": 0 if (not_null or pk) else 1,
                "is_primary_key": 1 if pk else 0,
                "references_to": fks.get(column),
                "allowed_values": allowed.get((table, column)),
            })
    mem.close()
    return columns


def column_rows(columns):
    rows = []
    for col in columns:
        key = (col["table"], col["column"])
        description, example, is_pii, note = COLUMN_DRAFTS.get(key, ("", None, 0, UNDRAFTED_NOTE))
        rows.append((
            col["table"], col["column"], col["data_type"], col["is_nullable"],
            col["is_primary_key"], col["references_to"], col["allowed_values"],
            description or "(undocumented)", example, is_pii,
            1 if note else 0, note, COLUMN_SYNONYMS.get(key),
        ))
    return rows


def split_list(text):
    return [part.strip() for part in text.split(",") if part.strip()] if text else []


def find_synonym_clashes(entries):
    """
    entries: (owner, synonyms_text, is_ambiguous). Returns phrases claimed by more than
    one owner where at least one of those owners is not flagged ambiguous.
    """
    owners = {}
    for owner, synonyms, _ in entries:
        for phrase in split_list(synonyms):
            owners.setdefault(phrase.lower(), set()).add(owner)
    flagged = {owner for owner, _, ambiguous in entries if ambiguous}
    return {phrase: sorted(who) for phrase, who in owners.items()
            if len(who) > 1 and not who <= flagged}


def check_glossary(columns):
    """Fail loudly on glossary entries that point at nothing or clash with each other."""
    known_columns = {f"{c['table']}.{c['column']}" for c in columns}
    known_metrics = {m["metric_name"] for m in METRICS}
    problems = []
    for entry in GLOSSARY:
        for ref in split_list(entry["related_columns"]):
            if ref not in known_columns:
                problems.append(f"{entry['term']}: unknown column {ref}")
        if entry["metric_name"] and entry["metric_name"] not in known_metrics:
            problems.append(f"{entry['term']}: unknown metric {entry['metric_name']}")
        if entry["kind"] == "metric" and not entry["metric_name"]:
            problems.append(f"{entry['term']}: metric term without metric_name")
        if entry["kind"] in ("entity", "value", "time") and entry["is_answerable"] \
                and not entry["sql_hint"]:
            problems.append(f"{entry['term']}: answerable {entry['kind']} without sql_hint")

    # A phrase may belong to one term only, counting each term's own name as a phrase.
    glossary_clashes = find_synonym_clashes(
        [(e["term"], f"{e['term']}, {e['synonyms'] or ''}", e["is_ambiguous"]) for e in GLOSSARY])
    column_clashes = find_synonym_clashes(
        [(f"{t}.{c}", s, 0) for (t, c), s in COLUMN_SYNONYMS.items()])
    for phrase, who in {**glossary_clashes, **column_clashes}.items():
        problems.append(f"synonym {phrase!r} claimed by {who}")
    for key in COLUMN_SYNONYMS:
        if f"{key[0]}.{key[1]}" not in known_columns:
            problems.append(f"synonyms for unknown column {key[0]}.{key[1]}")

    if problems:
        sys.exit("Glossary problems:\n  " + "\n  ".join(problems))


# -----------------------------------------------------------------------------
#  Term lookup (for the agent): exact match first, then with plurals made singular
# -----------------------------------------------------------------------------
def singular(word):
    """Singular form of one lower-case word; words that only look plural are kept."""
    if len(word) <= 2 or word.endswith(("ss", "us", "is")):
        return word                                   # e.g. "as", "status", "analysis"
    if word.endswith("ies"):
        return word[:-3] + "y"                        # queries -> query
    if word.endswith(("uses", "sses", "ches", "shes", "xes")):
        return word[:-2]                              # statuses -> status, boxes -> box
    if word.endswith("s"):
        return word[:-1]                              # tickets -> ticket, changes -> change
    return word


def find_term(conn, phrase):
    """
    Look a user phrase up in meta_glossary by term name or synonym, ignoring case.
    Tries the phrase as written, then with every word made singular ("P1s" -> "p1",
    "high-risk changes" -> "high-risk change"). Returns the glossary row as a dict, or None.
    """
    index = {}
    for row in conn.execute("SELECT * FROM meta_glossary ORDER BY term"):
        entry = dict(zip([d[0] for d in conn.execute("SELECT * FROM meta_glossary LIMIT 0").description], row))
        for name in [entry["term"]] + split_list(entry["synonyms"]):
            index.setdefault(name.lower(), entry)
    words = phrase.lower().split()
    for candidate in (" ".join(words), " ".join(singular(w) for w in words)):
        if candidate in index:
            return index[candidate]
    return None


# Plural and variant phrases the build proves find_term resolves (phrase -> expected term).
LOOKUP_CHECKS = {
    "tickets": "incident",
    "incidents": "incident",
    "teams": "assignment group",
    "CRs": "change",
    "changes": "change",
    "P1s": "critical priority",
    "Sev1": "critical priority",
    "high-risk changes": "high-risk change",
    "open incidents": "open incident",
    "cancelled incidents": "cancelled incident",
    "reopened incidents": "reopened incident",
    "engineers": "user",
    "managers": "manager",
    "SLA targets": "SLA target",
    "last 30 days": "last 30 days",
    "assignees": "assignee",
    "SLA compliance rate": "SLA compliance",
    "escalated incidents": "escalation",
    "predict": "forecast",
    "last quarter": "last quarter",
    "agent resolved": "agent activity",
    "running totals": "running total",
    "medians": "median",
    "resolved by each agent": "agent activity",
}


ALIAS_FROM = {
    "i": "incidents i",
    "c": "changes c",
    "u": "users u",
    "g": "assignment_groups g",
    "s": "sla_targets s",
}


def hint_test_queries(entry):
    """Queries that prove a glossary sql_hint runs, with placeholders filled with samples."""
    hint = entry["sql_hint"]
    if entry["kind"] == "entity":
        return [f"SELECT COUNT(*) FROM {hint}"]

    samples = [hint.replace("{n}", "1")]
    if "{time_column}" in hint:
        samples = [s.replace("{time_column}", col)
                   for s in samples for col in ("i.opened_at", "c.planned_start")]

    queries = []
    for sample in samples:
        aliases = set(re.findall(r"\b([icugs])\.", sample))
        if "i" in aliases or not aliases:
            source = "incidents i"
            if "s" in aliases:
                source += " JOIN sla_targets s ON s.priority = i.priority"
            if "g" in aliases:
                source += " JOIN assignment_groups g ON g.id = i.assignment_group_id"
        else:
            (alias,) = aliases  # non-incident hints use a single table
            source = ALIAS_FROM[alias]
        queries.append(f"SELECT COUNT(*) FROM {source} WHERE {sample}")
    return queries


def check_drafts(columns):
    """Fail loudly on drafts that no longer match schema.sql."""
    in_schema = {(c["table"], c["column"]) for c in columns}
    stale = sorted(set(COLUMN_DRAFTS) - in_schema)
    if stale:
        sys.exit(f"Drafts for columns not in schema.sql: {stale}")
    for col in columns:
        draft = COLUMN_DRAFTS.get((col["table"], col["column"]))
        if draft and col["allowed_values"] and draft[1] not in col["allowed_values"].split(", "):
            sys.exit(f"Example {draft[1]!r} for {col['table']}.{col['column']} "
                     f"is not one of: {col['allowed_values']}")


# -----------------------------------------------------------------------------
#  Build
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Build the meta_* semantic catalog.")
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help="database to add the catalog to (default db/tickets.sqlite)")
    db_path = parser.parse_args().db.resolve()
    if not db_path.exists():
        sys.exit(f"{db_path} not found. Run: python db/seed.py")

    columns = read_schema()
    check_drafts(columns)
    check_glossary(columns)
    check_tables_and_joins(columns)
    rows = column_rows(columns)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(META_DDL)
    with conn:
        conn.executemany(
            "INSERT INTO meta_columns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.executemany(
            f"INSERT INTO meta_metrics ({', '.join(METRIC_FIELDS)}) "
            f"VALUES ({', '.join('?' for _ in METRIC_FIELDS)})",
            [[m[f] for f in METRIC_FIELDS] for m in METRICS])
        conn.executemany(
            "INSERT INTO meta_tables VALUES (?, ?, ?)",
            [(t, d, g) for t, (d, g) in TABLE_DRAFTS.items()])
        conn.executemany("INSERT INTO meta_joins VALUES (?, ?, ?, ?, ?, ?)", JOINS)
        conn.executemany("INSERT INTO meta_settings VALUES (?, ?)",
                         [("as_of", AS_OF), ("dialect", DIALECT.name),
                          ("built_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))])
        conn.executemany(
            f"INSERT INTO meta_glossary ({', '.join(GLOSSARY_FIELDS)}) "
            f"VALUES ({', '.join('?' for _ in GLOSSARY_FIELDS)})",
            [[g[f] for f in GLOSSARY_FIELDS] for g in GLOSSARY])

    print(f"Built semantic catalog in {db_path.name} (as of {AS_OF})")
    for table in ["meta_tables", "meta_columns", "meta_glossary", "meta_metrics", "meta_joins"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<14} {count:>3}")

    flagged = conn.execute(
        "SELECT table_name, column_name, ambiguity_note FROM meta_columns "
        "WHERE is_ambiguous = 1 ORDER BY table_name, column_name").fetchall()
    print(f"\nColumns flagged as ambiguous: {len(flagged)}")
    for table, column, note in flagged:
        print(f"  {table}.{column}: {note}")

    # Prove each stored fragment runs as-is: read it back from the catalog and execute it.
    print("\nMetric check (composed from meta_metrics, whole table):")
    conn.row_factory = sqlite3.Row
    for metric in conn.execute("SELECT * FROM meta_metrics ORDER BY metric_name"):
        value = conn.execute(compose_metric_sql(dict(metric))).fetchone()[0]
        print(f"  {metric['metric_name']:<16} {value:,.4f} {metric['unit']}")

    # Prove each glossary hint runs as stored; show the row count it selects.
    print("\nGlossary check (each sql_hint run from meta_glossary):")
    glossary = conn.execute("SELECT * FROM meta_glossary ORDER BY kind, term").fetchall()
    for entry in glossary:
        if not entry["sql_hint"]:
            continue
        counts = []
        for query in hint_test_queries(dict(entry)):
            try:
                counts.append(conn.execute(query).fetchone()[0])
            except sqlite3.Error as exc:
                sys.exit(f"Glossary hint for {entry['term']!r} failed: {exc}\n  {query}")
        flag = "  [ambiguous]" if entry["is_ambiguous"] else ""
        print(f"  {entry['kind']:<7} {entry['term']:<22} rows={'/'.join(map(str, counts))}{flag}")

    # Prove plural/variant phrases resolve to the right glossary term.
    wrong = []
    for phrase, expected in LOOKUP_CHECKS.items():
        found = find_term(conn, phrase)
        if not found or found["term"] != expected:
            wrong.append(f"{phrase!r} -> {found['term'] if found else None} (expected {expected!r})")
    if wrong:
        sys.exit("Term lookup problems:\n  " + "\n  ".join(wrong))
    print(f"\nTerm lookup check: {len(LOOKUP_CHECKS)} plural/variant phrases resolve correctly")

    unanswerable = [e["term"] for e in glossary if not e["is_answerable"]]
    ambiguous = [e["term"] for e in glossary if e["is_ambiguous"]]
    print(f"\nGlossary terms: {len(glossary)}  |  ambiguous: {', '.join(ambiguous)}")
    print(f"Not answerable from this data: {', '.join(unanswerable)}")

    conn.close()


if __name__ == "__main__":
    main()
