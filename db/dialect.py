"""
SQL dialect helpers: the few date/time expressions this project needs, written once per
database engine. Everything else the platform generates is plain ANSI SQL.

    from dialect import DIALECT            # chosen by DB_DIALECT (default sqlite)
    DIALECT.minutes_between("i.resolved_at", "i.opened_at")
    DIALECT.date_from("'2026-09-28'", "start of month", "-1 month")
    DIALECT.month("i.opened_at")

The semantic catalog (semantics/build_catalog.py) and the API's own checks
(api/services.py) build their SQL fragments through these helpers, so the stored catalog
text is correct for the engine it was built for. The SQLite output is the historical
wording, byte for byte; the PostgreSQL output is written from the documentation and has
NOT been run against a live PostgreSQL yet (no server available here). Still SQLite-only:
the read-only connection and authorizer in agent/nl2sql.py and the STRICT schema in
db/schema.sql (see db/schema.postgres.sql for the PostgreSQL version of the tables).

Standard library only.
"""

import os
import re

_MOD = re.compile(r"^([+-]?\d+)\s+(day|days|month|months|year|years)$")


class Dialect:
    name = "sqlite"
    label = "SQLite"
    timestamp_note = "Timestamps are TEXT 'YYYY-MM-DD HH:MM:SS' UTC."

    def minutes_between(self, later, earlier):
        """Wall-clock minutes from `earlier` to `later` (both timestamp expressions)."""
        return f"(julianday({later}) - julianday({earlier})) * 1440"

    def date_from(self, base, *modifiers):
        """
        A DATE built from `base` (a quoted literal or column) and SQLite-style modifiers:
        'start of month', 'start of year', '+7 days', '-1 month', 'weekday 1' (next Monday,
        or the same day if it already is one).
        """
        parts = [base] + [f"'{m}'" for m in modifiers]
        return f"date({', '.join(parts)})"

    def month(self, column):
        """The calendar month of a timestamp as 'YYYY-MM'."""
        return f"strftime('%Y-%m', {column})"


class Postgres(Dialect):
    name = "postgres"
    label = "PostgreSQL"
    timestamp_note = "Timestamps are TIMESTAMP columns in UTC; compare them with 'YYYY-MM-DD HH:MM:SS' literals."

    def minutes_between(self, later, earlier):
        return f"EXTRACT(EPOCH FROM (({later})::timestamp - ({earlier})::timestamp)) / 60"

    def date_from(self, base, *modifiers):
        expr = f"({base})::date"
        for m in modifiers:
            if m == "start of month":
                expr = f"date_trunc('month', {expr})::date"
            elif m == "start of year":
                expr = f"date_trunc('year', {expr})::date"
            elif m.startswith("weekday "):
                dow = int(m.split()[1])  # SQLite: 0 = Sunday ... 6 = Saturday, same as PostgreSQL's dow
                expr = (f"({expr} + (({dow} - EXTRACT(DOW FROM {expr})::int + 7) % 7) "
                        f"* interval '1 day')::date")
            else:
                match = _MOD.match(m)
                if not match:
                    raise ValueError(f"unsupported date modifier {m!r}")
                amount, unit = int(match.group(1)), match.group(2).rstrip("s")
                sign = "+" if amount >= 0 else "-"
                expr = f"({expr} {sign} interval '{abs(amount)} {unit}')::date"
        return expr

    def month(self, column):
        return f"to_char({column}, 'YYYY-MM')"


DIALECTS = {"sqlite": Dialect(), "postgres": Postgres(), "postgresql": Postgres()}


def get(name=None):
    """The dialect named by `name` or the DB_DIALECT environment variable (default sqlite)."""
    key = (name or os.getenv("DB_DIALECT") or "sqlite").strip().lower()
    if key not in DIALECTS:
        raise ValueError(f"unknown DB_DIALECT {key!r}; choose sqlite or postgres")
    return DIALECTS[key]


DIALECT = get()
