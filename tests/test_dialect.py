"""db/dialect.py: the SQLite output is the historical wording; the PostgreSQL output is well-formed."""

import sqlite3

import pytest

import dialect


def test_sqlite_expressions_are_the_historical_wording():
    d = dialect.get("sqlite")
    assert d.minutes_between("i.resolved_at", "i.opened_at") == \
        "(julianday(i.resolved_at) - julianday(i.opened_at)) * 1440"
    assert d.date_from("'2026-09-28'", "start of month", "-1 month") == \
        "date('2026-09-28', 'start of month', '-1 month')"
    assert d.month("i.opened_at") == "strftime('%Y-%m', i.opened_at)"


@pytest.mark.parametrize("modifiers, expected", [
    (("start of month", "-1 month"), "2026-08-01"),
    (("start of month",), "2026-09-01"),
    (("-6 days", "weekday 1", "-7 days"), "2026-09-21"),   # last week's Monday
    (("-6 days", "weekday 1"), "2026-09-28"),              # this week's Monday (as-of is a Monday)
    (("-6 days", "weekday 1", "+7 days"), "2026-10-05"),   # next week's Monday
    (("-30 days",), "2026-08-29"),
    (("start of year",), "2026-01-01"),
])
def test_sqlite_date_from_matches_the_glossary_windows(modifiers, expected):
    sql = dialect.get("sqlite").date_from("'2026-09-28'", *modifiers)
    assert sqlite3.connect(":memory:").execute(f"SELECT {sql}").fetchone()[0] == expected


def test_postgres_expressions_are_well_formed():
    d = dialect.get("postgres")
    assert d.minutes_between("a", "b") == "EXTRACT(EPOCH FROM ((a)::timestamp - (b)::timestamp)) / 60"
    assert d.date_from("'2026-09-28'", "start of month", "-1 month") == \
        "(date_trunc('month', ('2026-09-28')::date)::date - interval '1 month')::date"
    assert "EXTRACT(DOW FROM" in d.date_from("'2026-09-28'", "weekday 1")
    assert d.month("x") == "to_char(x, 'YYYY-MM')"
    with pytest.raises(ValueError):
        d.date_from("'2026-09-28'", "start of week")


def test_unknown_dialect_is_rejected():
    with pytest.raises(ValueError):
        dialect.get("oracle")
