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


# --- SQL lint: valid SQL that returns a plausible but wrong number ------------------------------
@pytest.fixture
def conn(db_path):
    connection = nl2sql.connect_readonly(db_path)
    yield connection
    connection.close()


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM incidents i WHERE i.opened_at >= date('2026-09-28', 'start of quarter')",
    "SELECT date('2026-09-28', 'start of week')",
    "SELECT strftime('%Y', i.opened_at, '-1 quarter') FROM incidents i",
])
def test_lint_flags_unknown_date_modifiers(conn, sql):
    assert any("not a SQLite date modifier" in p for p in nl2sql.lint_sql(conn, sql))


def test_unknown_modifier_really_returns_null_not_an_error(conn):
    # the reason the lint exists: SQLite accepts the query and every comparison silently fails
    assert conn.execute("SELECT date('2026-09-28', 'start of quarter')").fetchone() == (None,)


@pytest.mark.parametrize("sql", [
    "SELECT date('2026-09-28', 'start of month', '-1 month', 'weekday 1', '+7 days')",
    "SELECT strftime('%Y-%m', i.opened_at, 'start of year') FROM incidents i",
    "SELECT date('2026-09-28', '-30 days'), datetime('2026-09-28 10:00:00', '+90 minutes')",
    "SELECT COUNT(*) FROM incidents WHERE short_desc = 'date(x, ''start of quarter'')'",
])
def test_lint_accepts_valid_modifiers(conn, sql):
    assert nl2sql.lint_sql(conn, sql) == []


@pytest.mark.parametrize("sql", [
    "SELECT g.name, COUNT(i.id), COUNT(c.id) FROM assignment_groups g "
    "LEFT JOIN incidents i ON i.assignment_group_id = g.id "
    "LEFT JOIN changes c ON c.assignment_group_id = g.id GROUP BY g.id",
    "SELECT g.name, COUNT(i.id), COUNT(u.id) FROM assignment_groups g "
    "LEFT JOIN incidents i ON i.assignment_group_id = g.id "
    "LEFT JOIN users u ON u.assignment_group_id = g.id AND u.role = 'agent' GROUP BY g.id",
    "SELECT u.id, COUNT(i.id) FROM incidents i JOIN users u "
    "ON i.assignment_group_id = u.assignment_group_id GROUP BY u.id",
])
def test_lint_flags_join_fan_out(conn, sql):
    assert any("inflated" in p for p in nl2sql.lint_sql(conn, sql))


@pytest.mark.parametrize("sql", [
    # one child table per query, counts in their own sub-SELECTs
    "SELECT g.name, (SELECT COUNT(*) FROM incidents i WHERE i.assignment_group_id = g.id), "
    "(SELECT COUNT(*) FROM changes c WHERE c.assignment_group_id = g.id) FROM assignment_groups g",
    "WITH a AS (SELECT assignment_group_id, COUNT(*) n FROM incidents GROUP BY 1), "
    "b AS (SELECT assignment_group_id, COUNT(*) m FROM users GROUP BY 1) "
    "SELECT g.name, a.n, b.m FROM assignment_groups g "
    "LEFT JOIN a ON a.assignment_group_id = g.id LEFT JOIN b ON b.assignment_group_id = g.id",
    "SELECT g.name, COUNT(i.id) FROM assignment_groups g "
    "LEFT JOIN incidents i ON i.assignment_group_id = g.id AND i.priority = 1 GROUP BY g.id",
    "SELECT COUNT(*) FROM incidents i JOIN sla_targets s ON s.priority = i.priority",
    # incidents joined to users or changes on their OWN foreign key: many-to-one, no fan-out
    "SELECT i.assignee_id, u.role, COUNT(*) FROM incidents i JOIN users u ON u.id = i.assignee_id "
    "GROUP BY i.assignee_id, u.role",
    "SELECT COUNT(*) FROM incidents i JOIN users u ON i.caller_id = u.id WHERE u.role = 'manager'",
    "SELECT c.id, COUNT(i.id) FROM changes c JOIN incidents i ON i.caused_by_change_id = c.id "
    "GROUP BY c.id ORDER BY COUNT(i.id) DESC LIMIT 1",
])
def test_lint_accepts_correct_aggregates(conn, sql):
    assert nl2sql.lint_sql(conn, sql) == []


def test_lint_flags_filter_on_parent_inside_left_join(conn):
    sql = ("SELECT strftime('%Y-%m', i.opened_at), COUNT(i.id) FROM incidents i "
           "LEFT JOIN assignment_groups g ON i.assignment_group_id = g.id AND g.name = 'Network' "
           "GROUP BY 1")
    assert any("removes no incidents rows" in p for p in nl2sql.lint_sql(conn, sql))


def test_lint_passes_all_golden_reference_sql(conn):
    import yaml
    for name in ("golden_set.yaml", "golden_set_large.yaml"):
        path = nl2sql.ROOT / "evals" / name
        for q in yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]:
            sqls = [q["reference_sql"]] if q.get("reference_sql") else []
            sqls += [a["reference_sql"] for a in q.get("alternatives") or []]
            resolved = nl2sql.resolve_terms(conn, q["question"])
            children = nl2sql.child_tables(conn)
            for sql in sqls:
                assert nl2sql.lint_sql(conn, sql) == [], q["id"]
                assert nl2sql.lint_question(q["question"], sql, resolved, children) == [], q["id"]


BAD_QUARTER = "```sql\nSELECT COUNT(*) FROM incidents i WHERE i.opened_at >= date('2026-09-28', 'start of quarter')\n```"
GOOD_QUARTER = "```sql\nSELECT COUNT(*) FROM incidents i WHERE i.opened_at >= '2026-04-01' AND i.opened_at < '2026-07-01'\n```"


def test_translate_sends_a_lint_problem_back_once_and_uses_the_fix(conn, fake_model):
    replies, calls = fake_model
    replies += [BAD_QUARTER, GOOD_QUARTER]
    result = nl2sql.translate("How many incidents were opened last quarter?", conn)
    assert len(calls) == 2 and "start of quarter" in calls[1]["user"]
    assert result["unsafe"] is None and "2026-04-01" in result["sql"]
    assert result["lint"] and "not a SQLite date modifier" in result["lint"][0]


def test_translate_blocks_sql_that_still_fails_the_lint(conn, fake_model):
    replies, calls = fake_model
    replies += [BAD_QUARTER, BAD_QUARTER]
    result = nl2sql.translate("How many incidents were opened last quarter?", conn)
    assert len(calls) == 2 and "not a SQLite date modifier" in result["unsafe"]


def test_clean_sql_costs_no_extra_model_call(conn, fake_model):
    replies, calls = fake_model
    replies.append(GOOD_QUARTER)
    result = nl2sql.translate("How many incidents were opened last quarter?", conn)
    assert len(calls) == 1 and result["lint"] == []


@pytest.mark.parametrize("question", [
    "Which category of incident is most common?",
    "What is the email address of the admin?",
    "What was the customer satisfaction score last month?",
    "How many incidents per configuration item?",
])
def test_unanswerable_questions_are_refused_before_the_model(conn, fake_model, question):
    _, calls = fake_model
    assert nl2sql.translate(question, conn)["refusal"] and calls == []


@pytest.mark.parametrize("question", [
    "How many incidents did the Network team resolve last month?",
    "How many incidents were resolved by the Service Desk?",
    "How many agents does each team have?",
    "How many incidents does each team have per agent?",
    # answerable since 2026-10-02 (the schema gained the columns)
    "Which agent resolved the most incidents?",
    "How many incidents were resolved by each agent?",
    "Who is the assignee of incident 101?",
    "How many incidents were escalated?",
    "Predict how many incidents will be opened next month",
    "What was the response time for P1 incidents last month?",
    "What was the total downtime last month?",
    "How many incidents were caused by a change?",
    "How many changes overran their window?",
    "How many high-impact incidents are open?",
])
def test_team_and_person_questions_are_not_refused(conn, fake_model, question):
    assert nl2sql.translate(question, conn)["refusal"] is None


def test_no_glossary_term_from_the_original_ten_is_unanswerable(conn):
    """The ten terms flagged is_answerable = 0 until 2026-10-02 are all answerable now."""
    fixed = ["assignee", "caller", "response time", "downtime", "impact", "actual change window",
             "change-caused incident", "escalation", "forecast", "agent activity"]
    rows = dict(conn.execute("SELECT term, is_answerable FROM meta_glossary").fetchall())
    assert all(rows[term] == 1 for term in fixed), {t: rows.get(t) for t in fixed}


# --- lint part 2: SQL that does not match what the question asked ------------------------------
def soft(conn, question, sql):
    return nl2sql.lint_question(question, sql, nl2sql.resolve_terms(conn, question),
                                nl2sql.child_tables(conn))


OPEN_SQL = ("SELECT g.name, COUNT(i.id) FROM assignment_groups g LEFT JOIN incidents i "
            "ON i.assignment_group_id = g.id AND i.priority = 1 "
            "AND i.status IN ('New', 'In Progress', 'On Hold') GROUP BY g.id")


@pytest.mark.parametrize("question, sql, fragment", [
    ("How many P1 incidents does each team have?", OPEN_SQL, "keeps only open incidents"),
    ("Show the 5 most recently opened incidents",
     "SELECT i.id FROM incidents i WHERE i.status IN ('New', 'In Progress', 'On Hold') "
     "ORDER BY i.opened_at DESC LIMIT 5", "keeps only open incidents"),
    ("How many changes start on a weekend?",
     "SELECT COUNT(*) FROM changes c WHERE strftime('%w', c.planned_start) IN ('0', '6') "
     "AND c.status <> 'Cancelled'", "leaves out cancelled rows"),
    ("Show the oldest open incident",
     "SELECT MIN(i.opened_at) FROM incidents i WHERE i.status IN ('New', 'In Progress', 'On Hold')",
     "returns one aggregate value"),
    ("List all P1 incidents that are still open",
     "SELECT COUNT(i.id) FROM incidents i WHERE i.priority = 1", "returns one aggregate value"),
    ("How many teams have more than 10 open incidents?",
     "SELECT COUNT(g.id) FROM assignment_groups g LEFT JOIN incidents i "
     "ON i.assignment_group_id = g.id GROUP BY g.id HAVING COUNT(i.id) > 10", "one unlabelled row"),
    ("What is the average number of changes per team?",
     "SELECT g.name, COUNT(c.id) FROM assignment_groups g LEFT JOIN changes c "
     "ON c.assignment_group_id = g.id GROUP BY g.name", "is one number"),
    ("What is the average number of incidents per month?",
     "SELECT COUNT(i.id) / 12.0 FROM incidents i", "fixed number of months"),
    ("How many incidents does each team have per agent?",
     "SELECT g.name, COUNT(i.id), COUNT(u.id) FROM assignment_groups g "
     "LEFT JOIN incidents i ON i.assignment_group_id = g.id "
     "LEFT JOIN users u ON u.assignment_group_id = g.id GROUP BY g.id", "is a ratio"),
    ("How many incidents were opened between 9am and 5pm?",
     "SELECT COUNT(*) FROM incidents i WHERE i.opened_at >= '2026-09-28 09:00:00' "
     "AND i.opened_at < '2026-09-28 17:00:00'", "applies to every date"),
    ("Which team has the highest percentage of P1 incidents?",
     "SELECT g.name, 100.0 * COUNT(i.id) / SUM(COUNT(i.id)) OVER () FROM assignment_groups g "
     "LEFT JOIN incidents i ON i.assignment_group_id = g.id AND i.priority = 1 GROUP BY g.id",
     "team's own count over the team's own total"),
    ("Which team has the highest percentage of P1 incidents?",
     "SELECT g.name, ROUND(100.0 * COUNT(i.id) / NULLIF(SUM(CASE WHEN i.priority = 1 THEN 1 ELSE 0 "
     "END), 0), 1) AS pct FROM assignment_groups g LEFT JOIN incidents i ON g.id = i.assignment_group_id "
     "GROUP BY g.id ORDER BY pct DESC LIMIT 1", "upside down"),
    ("Predict how many incidents will be opened next month",
     "SELECT AVG(n) FROM (SELECT COUNT(*) AS n FROM incidents i WHERE i.opened_at >= '2026-10-01' "
     "AND i.opened_at < '2026-11-01' GROUP BY strftime('%Y-%m', i.opened_at))", "window exactly"),
    ("Which teams had zero SLA breaches last month?",
     "SELECT g.name, COUNT(i.id) FROM assignment_groups g LEFT JOIN incidents i ON g.id = i.assignment_group_id "
     "JOIN sla_targets s ON s.priority = i.priority WHERE i.status IN ('Resolved', 'Closed') "
     "GROUP BY g.id HAVING COUNT(i.id) = 0", "after a LEFT JOIN"),
    ("How many P1 incidents does each team have?",
     "SELECT g.name, COUNT(i.id) FROM assignment_groups g LEFT JOIN incidents i ON g.id = i.assignment_group_id "
     "WHERE i.priority = 1 GROUP BY g.id", "WHERE clause filters i.*"),
    ("How many high-risk changes are planned this month?",
     "SELECT COUNT(*) FROM changes c WHERE c.planned_start >= '2026-09-28' "
     "AND c.planned_start < date('2026-09-28', 'start of month', '+1 month') AND c.risk = 'High'",
     "first day of the period"),
])
def test_soft_lint_flags_a_mismatch(conn, question, sql, fragment):
    assert any(fragment in p for p in soft(conn, question, sql))


@pytest.mark.parametrize("question, sql", [
    ("How many P1 incidents are still open?", OPEN_SQL),                     # open was asked for
    ("How many incidents are overdue?", OPEN_SQL),                            # the term's hint is open
    ("How many high-risk changes are scheduled next week?",
     "SELECT COUNT(*) FROM changes c WHERE c.risk = 'High' AND c.status <> 'Cancelled'"),
    ("Show the 5 most recently opened incidents",
     "SELECT i.id FROM incidents i ORDER BY i.opened_at DESC LIMIT 5"),
    ("How many incidents are there?", "SELECT COUNT(*) FROM incidents i"),
    ("Show the average resolution time", "SELECT AVG(1.0) FROM incidents i"),
    ("Which team has the most incidents per agent?",
     "SELECT g.name FROM assignment_groups g ORDER BY 1.0 * (SELECT COUNT(*) FROM incidents i) / 5"),
    ("How many incidents were opened at 9am on 2026-09-01?",
     "SELECT COUNT(*) FROM incidents i WHERE i.opened_at >= '2026-09-01 09:00:00'"),
    ("What share of all incidents does each team have?",
     "SELECT g.name, 1.0 * COUNT(i.id) / SUM(COUNT(i.id)) OVER () FROM assignment_groups g "
     "LEFT JOIN incidents i ON i.assignment_group_id = g.id GROUP BY g.id"),
    ("How many incidents does each team have?",
     "SELECT COUNT(i.id) FROM incidents i GROUP BY i.assignment_group_id"),   # 'each' asks for groups
    ("Which team has the highest percentage of P1 incidents?",
     "SELECT g.name FROM incidents i JOIN assignment_groups g ON g.id = i.assignment_group_id "
     "GROUP BY g.id ORDER BY 1.0 * SUM(CASE WHEN i.priority = 1 THEN 1 ELSE 0 END) / COUNT(*) DESC LIMIT 1"),
    ("Predict how many incidents will be opened next month",
     "SELECT AVG(n) FROM (SELECT COUNT(*) AS n FROM incidents i WHERE i.opened_at >= '2026-06-01' "
     "AND i.opened_at < '2026-09-01' GROUP BY strftime('%Y-%m', i.opened_at))"),
    ("Which teams had zero SLA breaches last month?",        # conditions inside the ON clauses
     "SELECT g.name FROM assignment_groups g LEFT JOIN incidents i ON i.assignment_group_id = g.id "
     "AND i.status IN ('Resolved', 'Closed') LEFT JOIN sla_targets s ON s.priority = i.priority "
     "GROUP BY g.name HAVING COUNT(i.id) = 0"),
    ("How many cancelled incidents does the Network team have?",   # WHERE on the parent is fine
     "SELECT COUNT(i.id) FROM assignment_groups g LEFT JOIN incidents i ON i.assignment_group_id = g.id "
     "AND i.status = 'Cancelled' WHERE g.name = 'Network'"),
    ("How many high-risk changes are planned this month?",
     "SELECT COUNT(*) FROM changes c WHERE c.planned_start >= '2026-09-01' "
     "AND c.planned_start < '2026-10-01' AND c.risk = 'High'"),
])
def test_soft_lint_accepts_matching_sql(conn, question, sql):
    assert soft(conn, question, sql) == []


def test_syntax_error_is_caught_before_running(conn):
    bad = "SELECT COUNT(*) FROM incidents WHERE opened_at < '2026-09-28', '+1 day'"
    assert any("SQLite rejects this SQL" in p for p in nl2sql.lint_sql(conn, bad))


OPEN_REPLY = "```sql\n" + OPEN_SQL + "\n```"
ALL_REPLY = ("```sql\nSELECT g.name, COUNT(i.id) FROM assignment_groups g LEFT JOIN incidents i "
             "ON i.assignment_group_id = g.id AND i.priority = 1 GROUP BY g.id\n```")


def test_soft_problem_is_repaired_once(conn, fake_model):
    replies, calls = fake_model
    replies += [OPEN_REPLY, ALL_REPLY]
    result = nl2sql.translate("How many P1 incidents does each team have?", conn)
    assert len(calls) == 2 and "keeps only open" in calls[1]["user"]
    assert "On Hold" not in result["sql"] and result["unsafe"] is None


def test_soft_problem_never_blocks_the_query(conn, fake_model):
    replies, calls = fake_model
    replies += [OPEN_REPLY, OPEN_REPLY]
    result = nl2sql.translate("How many P1 incidents does each team have?", conn)
    assert len(calls) == 2 and result["unsafe"] is None and "On Hold" in result["sql"]


def test_follow_up_questions_skip_the_soft_checks(conn, fake_model):
    replies, calls = fake_model
    replies.append(OPEN_REPLY)
    history = [{"question": "How many P1 incidents are open?", "sql": "SELECT 1"}]
    nl2sql.translate("and by team?", conn, history=history)
    assert len(calls) == 1
