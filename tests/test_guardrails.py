"""SQL guardrails: SELECT-only, one statement, row limit, personal data blocked, timeout."""

import sqlite3

import pytest

import nl2sql


@pytest.mark.parametrize("sql, reason", [
    ("DELETE FROM incidents", "not a SELECT statement"),
    ("SELECT 1; DROP TABLE incidents", "more than one statement"),
    ("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x", "forbidden keyword: INSERT"),
    ("SELECT * FROM incidents WHERE id IN (SELECT id FROM incidents) AND 1=1 UNION SELECT pragma", "forbidden keyword: PRAGMA"),
    ("", "empty SQL"),
])
def test_guard_rejects(sql, reason):
    with pytest.raises(nl2sql.UnsafeSQL, match=reason):
        nl2sql.guard_sql(sql)


def test_guard_appends_limit_and_keeps_existing():
    assert nl2sql.guard_sql("SELECT 1").endswith(f"LIMIT {nl2sql.MAX_ROWS}")
    assert nl2sql.guard_sql("SELECT 1 LIMIT 5;") == "SELECT 1 LIMIT 5"


def test_guard_ignores_keywords_and_semicolons_inside_strings():
    sql = "SELECT COUNT(*) FROM incidents WHERE short_desc = 'drop; delete'"
    assert nl2sql.guard_sql(sql).startswith(sql)


def test_extract_sql_reads_assumption():
    sql, assumption = nl2sql.extract_sql("```sql\n-- assumption: closed = Resolved or Closed\nSELECT 1\n```")
    assert sql == "SELECT 1" and assumption == "closed = Resolved or Closed"


def test_personal_data_blocked_even_with_star(db_path):
    conn = nl2sql.connect_readonly(db_path)
    try:
        for sql in ("SELECT name FROM users", "SELECT * FROM users", "SELECT u.name FROM users u LIMIT 1"):
            with pytest.raises(nl2sql.UnsafeSQL, match="personal data"):
                nl2sql.run_sql(conn, sql)
        columns, rows = nl2sql.run_sql(conn, "SELECT role, COUNT(*) FROM users GROUP BY role")
        assert columns == ["role", "COUNT(*)"] and len(rows) == 4
    finally:
        conn.close()


def test_database_is_read_only(db_path):
    conn = nl2sql.connect_readonly(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM incidents")
    finally:
        conn.close()


def test_slow_query_times_out(db_path):
    conn = nl2sql.connect_readonly(db_path)
    try:
        slow = ("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) "
                "SELECT COUNT(*) FROM n")
        with pytest.raises(sqlite3.OperationalError, match="timed out"):
            nl2sql.run_sql(conn, slow, timeout_ms=200)
    finally:
        conn.close()
