"""
Generate a golden eval set: every expected value comes from running its reference SQL.

    python evals/make_golden_set.py            # db/tickets.sqlite -> evals/golden_set.yaml
    python evals/make_golden_set.py --db db/tickets_large.sqlite --out evals/golden_set_large.yaml

The 15 questions and their reference SQL are defined once below (Q); only the expected rows
depend on the database. Regenerate whenever db/seed.py or the database size changes.
"""
import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path("db/tickets.sqlite")
DEFAULT_OUT = Path("evals/golden_set.yaml")
DEFAULT_COUNTS = (500, 100)  # incidents, changes built by a plain `python db/seed.py`
OPEN = "i.status IN ('New', 'In Progress', 'On Hold')"
FINISHED = "i.status IN ('Resolved', 'Closed')"
MINUTES = "(julianday(i.resolved_at) - julianday(i.opened_at)) * 1440"
BREACHED = f"{MINUTES} > s.target_minutes"
LAST_MONTH = "i.opened_at >= '2026-08-01' AND i.opened_at < '2026-09-01'"

Q = [
    # ---------------- easy lookups ----------------
    dict(id="E01", category="easy_lookup", question="How many incidents are there in total?",
         sql="SELECT COUNT(*) AS incidents FROM incidents"),
    dict(id="E02", category="easy_lookup", question="How many P1 incidents are currently open?",
         sql=f"SELECT COUNT(*) AS open_p1 FROM incidents i WHERE i.priority = 1 AND {OPEN}",
         notes="P1 = priority 1 (Critical). Open = New, In Progress or On Hold, not resolved_at IS NULL "
               "(that would also count Cancelled)."),
    dict(id="E03", category="easy_lookup", question="What is the SLA target for priority 2 incidents?",
         sql="SELECT target_minutes FROM sla_targets WHERE priority = 2",
         notes="480 minutes = 8 hours. An answer in hours must say 8."),
    dict(id="E04", category="easy_lookup", question="How many high-risk changes are there?",
         sql="SELECT COUNT(*) AS high_risk_changes FROM changes c WHERE c.risk = 'High'"),

    # ---------------- ambiguous date ranges ----------------
    dict(id="D01", category="date_range", question="How many incidents were opened last month?",
         sql=f"SELECT COUNT(*) AS incidents FROM incidents i WHERE {LAST_MONTH}",
         notes="As-of date is 2026-09-28, so last month = August 2026 (calendar month), "
               "filtered on opened_at. Using the real clock is a failure."),
    dict(id="D02", category="date_range", question="How many high-risk changes are scheduled next week?",
         sql="SELECT COUNT(*) AS high_risk_changes FROM changes c WHERE c.risk = 'High' "
             "AND c.status <> 'Cancelled' "
             "AND c.planned_start >= '2026-10-05' AND c.planned_start < '2026-10-12'",
         ambiguous=True,
         alternatives=[dict(reading="next 7 days / the as-of week (2026-09-28 to 2026-10-04)",
                            sql="SELECT COUNT(*) AS high_risk_changes FROM changes c WHERE c.risk = 'High' "
                                "AND c.status <> 'Cancelled' "
                                "AND c.planned_start >= '2026-09-28' AND c.planned_start < '2026-10-05'")],
         notes="2026-09-28 is a Monday. Default reading (glossary 'next week'): the following calendar "
               "week 2026-10-05 to 2026-10-11. The alternative reading is also accepted if the answer "
               "states its assumption."),
    dict(id="D03", category="date_range", question="How many incidents were opened in the past month?",
         sql="SELECT COUNT(*) AS incidents FROM incidents i "
             "WHERE i.opened_at >= date('2026-09-28', '-30 days') AND i.opened_at < '2026-09-28'",
         ambiguous=True,
         alternatives=[dict(reading="previous calendar month (August 2026)",
                            sql=f"SELECT COUNT(*) AS incidents FROM incidents i WHERE {LAST_MONTH}")],
         notes="'Past month' maps to 'last 30 days' in the glossary (2026-08-29 to 2026-09-27). "
               "Tests that it is not silently treated as 'last month'."),
    dict(id="D04", category="date_range", question="How many incidents were resolved last week?",
         sql="SELECT COUNT(*) AS incidents FROM incidents i WHERE i.status IN ('Resolved', 'Closed') "
             "AND i.resolved_at >= '2026-09-21' AND i.resolved_at < '2026-09-28'",
         notes="Last week = Monday 2026-09-21 to Sunday 2026-09-27. 'Resolved' means the filter must be on "
               "resolved_at, not opened_at (the metric default time_column)."),

    # ---------------- multi-table joins ----------------
    dict(id="J01", category="multi_table_join",
         question="Which assignment groups breached SLA most last month?",
         sql=f"SELECT g.name AS team, SUM(CASE WHEN {BREACHED} THEN 1 ELSE 0 END) AS breached "
             f"FROM incidents i JOIN sla_targets s ON s.priority = i.priority "
             f"JOIN assignment_groups g ON g.id = i.assignment_group_id "
             f"WHERE {FINISHED} AND {LAST_MONTH} GROUP BY g.name ORDER BY breached DESC, g.name",
         order_matters=True,
         notes="Ranked by breach count (the question says 'most'). Ranking by rate gives a different order "
               "(Database 28.6% first) and is a failure here."),
    dict(id="J02", category="multi_table_join", question="What is the SLA breach rate for each priority?",
         sql=f"SELECT i.priority, ROUND(100.0 * AVG(CASE WHEN {BREACHED} THEN 1.0 ELSE 0.0 END), 1) "
             f"AS breach_pct FROM incidents i JOIN sla_targets s ON s.priority = i.priority "
             f"WHERE {FINISHED} GROUP BY i.priority ORDER BY i.priority",
         tolerance=0.1,
         notes="Percent of resolved or closed incidents, all time. Uses metric sla_breach_rate."),
    dict(id="J03", category="multi_table_join", question="How many open incidents does each team have?",
         sql=f"SELECT g.name AS team, COUNT(i.id) AS open_incidents FROM assignment_groups g "
             f"LEFT JOIN incidents i ON i.assignment_group_id = g.id AND {OPEN} "
             f"GROUP BY g.name ORDER BY g.name"),
    dict(id="J04", category="multi_table_join", question="Which team has the most agents?",
         sql="SELECT g.name AS team, COUNT(*) AS agents FROM users u "
             "JOIN assignment_groups g ON g.id = u.assignment_group_id "
             "WHERE u.role = 'agent' GROUP BY g.name ORDER BY agents DESC LIMIT 1",
         notes="Agents only (role = 'agent'); team leads are not agents. Counting all users gives 12, "
               "which is a failure. Must not reveal user names."),

    # ---------------- known edge cases ----------------
    dict(id="K01", category="edge_case", question="Which teams had zero SLA breaches last month?",
         sql=f"SELECT g.name AS team FROM assignment_groups g "
             f"LEFT JOIN incidents i ON i.assignment_group_id = g.id AND {FINISHED} AND {LAST_MONTH} "
             f"LEFT JOIN sla_targets s ON s.priority = i.priority "
             f"GROUP BY g.name HAVING SUM(CASE WHEN {BREACHED} THEN 1 ELSE 0 END) = 0 "
             f"OR COUNT(i.id) = 0 ORDER BY g.name",
         notes="Group with a zero count. An inner join plus GROUP BY drops zero groups; the answer must "
               "still list Infrastructure."),
    dict(id="K02", category="edge_case", question="How many cancelled incidents does the Network team have?",
         sql="SELECT COUNT(i.id) AS cancelled FROM assignment_groups g "
             "LEFT JOIN incidents i ON i.assignment_group_id = g.id AND i.status = 'Cancelled' "
             "WHERE g.name = 'Network'",
         notes="Correct answer is 0, not an empty result or an error. The team exists but has no "
               "cancelled incidents."),
    dict(id="K03", category="edge_case", question="Who is the assignee of incident 101?",
         refusal=True,
         notes="Not answerable: incidents link to a team, not a person (glossary 'assignee', "
               "is_answerable = 0). Pass = the answer says the data does not record assignees and "
               "may offer the team instead; it must not join users and name a person."),
]


def run(conn, sql):
    cur = conn.execute(sql)
    return [d[0] for d in cur.description], [list(r) for r in cur.fetchall()]


def j(value):
    return json.dumps(value, ensure_ascii=False)


def block(text, indent):
    pad = " " * indent
    return "|\n" + "\n".join(pad + line for line in text.splitlines())


def pretty_sql(sql):
    for kw in [" FROM ", " LEFT JOIN ", " JOIN ", " WHERE ", " GROUP BY ", " HAVING ", " ORDER BY ", " LIMIT "]:
        sql = sql.replace(kw, "\n" + kw.strip() + " ")
    return sql


def main():
    parser = argparse.ArgumentParser(description="Generate a golden eval set from a database.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="database to compute expected rows from (default db/tickets.sqlite)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="YAML file to write (default evals/golden_set.yaml)")
    args = parser.parse_args()
    db_rel = args.db.as_posix()
    conn = sqlite3.connect(f"file:{(ROOT / args.db).resolve().as_posix()}?mode=ro", uri=True)

    counts_in_db = tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                         for t in ("incidents", "changes"))
    seed_cmd = "python db/seed.py"
    if counts_in_db != DEFAULT_COUNTS or args.db != DEFAULT_DB:
        seed_cmd += (f" --incidents {counts_in_db[0]} --changes {counts_in_db[1]} "
                     f"--out {db_rel}")

    out = [
        "# Golden eval set for the ITSM NL2SQL agent.",
        "#",
        "# Every expected value below was produced by running its reference_sql against",
        f"# {db_rel} built by `{seed_cmd}` (seed 42, as-of 2026-09-28). Rebuild the",
        "# database before evaluating; if seed.py changes, regenerate the expected rows.",
        "#",
        "# Scoring (execution accuracy, used by evals/run_evals.py and /run-evals):",
        "#   - pass when the agent's SQL returns the same rows as expected.rows",
        "#   - rows compare order-insensitively unless order_matters is true",
        "#   - numbers may differ by at most `tolerance` (default 0)",
        "#   - ambiguous questions also pass on any `alternatives` reading",
        "#   - refusal questions pass when the agent declines and explains why; no SQL is expected",
        "",
        "version: 1",
        'as_of: "2026-09-28"',
        f"database: {db_rel}",
        "",
        "questions:",
    ]
    counts = {}
    for item in Q:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
        out += ["", f"  - id: {item['id']}", f"    category: {item['category']}",
                f"    question: {j(item['question'])}"]
        if item.get("refusal"):
            out += ["    reference_sql: null", "    expected:", "      refusal: true"]
        else:
            cols, rows = run(conn, item["sql"])
            out += [f"    reference_sql: {block(pretty_sql(item['sql']), 6)}", "    expected:",
                    f"      columns: {j(cols)}", f"      rows: {j(rows)}"]
            out.append(f"    order_matters: {'true' if item.get('order_matters') else 'false'}")
            if "tolerance" in item:
                out.append(f"    tolerance: {item['tolerance']}")
        out.append(f"    ambiguous: {'true' if item.get('ambiguous') else 'false'}")
        if item.get("alternatives"):
            out.append("    alternatives:")
            for alt in item["alternatives"]:
                cols, rows = run(conn, alt["sql"])
                out += [f"      - reading: {j(alt['reading'])}",
                        f"        reference_sql: {block(pretty_sql(alt['sql']), 10)}",
                        f"        rows: {j(rows)}"]
        if item.get("notes"):
            out.append(f"    notes: {j(item['notes'])}")
    out_path = ROOT / args.out
    out_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {args.out.as_posix()} with {len(Q)} questions from {db_rel}: {counts}")


if __name__ == "__main__":
    main()
