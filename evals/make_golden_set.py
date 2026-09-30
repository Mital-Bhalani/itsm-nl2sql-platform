"""
Generate a golden eval set: every expected value comes from running its reference SQL.

    python evals/make_golden_set.py            # db/tickets.sqlite -> evals/golden_set.yaml
    python evals/make_golden_set.py --db db/tickets_large.sqlite --out evals/golden_set_large.yaml

The 51 questions and their reference SQL are defined once below (Q); only the expected rows
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
THIS_MONTH = "i.opened_at >= '2026-09-01' AND i.opened_at < '2026-09-28'"
MTTR = f"AVG({MINUTES})"
OVERDUE = f"{OPEN} AND (julianday('2026-09-28') - julianday(i.opened_at)) * 1440 > s.target_minutes"
BREACH_PCT = f"ROUND(100.0 * AVG(CASE WHEN {BREACHED} THEN 1.0 ELSE 0.0 END), 1)"

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

    # =====================================================================================
    #  Added 2026-09-30: 36 more questions a service manager would ask of this data (K12 last).
    #  Each answer was checked by hand against the seed facts before being added.
    # =====================================================================================

    # ---------------- easy lookups ----------------
    dict(id="E05", category="easy_lookup", question="How many open tickets are there?",
         sql=f"SELECT COUNT(*) AS open_tickets FROM incidents i WHERE {OPEN}",
         notes="Plural 'tickets' = incidents (glossary). Open = New, In Progress, On Hold: 50 at the "
               "default size. Counting resolved_at IS NULL also includes the 10 cancelled ones (60)."),
    dict(id="E06", category="easy_lookup", question="How many incidents are on hold?",
         sql="SELECT COUNT(*) AS on_hold FROM incidents i WHERE i.status = 'On Hold'"),
    dict(id="E07", category="easy_lookup", question="How many incidents have been reopened?",
         sql="SELECT COUNT(*) AS reopened FROM incidents i WHERE i.reopened_count > 0",
         notes="Reopened at least once (reopened_count > 0), not the sum of reopened_count."),
    dict(id="E08", category="easy_lookup", question="How many incidents were reopened more than once?",
         sql="SELECT COUNT(*) AS reopened_twice FROM incidents i WHERE i.reopened_count > 1",
         notes="Schema example question 4 as a count (the id list exceeds LIMIT 1000 on the large set). "
               "Strictly more than once: reopened_count > 1 (11 at the default size), not >= 1 (44)."),
    dict(id="E09", category="easy_lookup", question="How many agents do we have?",
         sql="SELECT COUNT(*) AS agents FROM users u WHERE u.role = 'agent'",
         notes="Role = 'agent' only (31). All users would be 40. Counting must not list names."),
    dict(id="E10", category="easy_lookup", question="How many low-risk changes were cancelled?",
         sql="SELECT COUNT(*) AS cancelled_low_risk FROM changes c "
             "WHERE c.risk = 'Low' AND c.status = 'Cancelled'",
         notes="Two filters on the same table; cancelled is a change status, not an incident status."),
    dict(id="E11", category="easy_lookup", question="What is the SLA target in hours for critical incidents?",
         sql="SELECT s.target_minutes / 60.0 AS target_hours FROM sla_targets s WHERE s.priority = 1",
         tolerance=0.01,
         notes="Critical = priority 1 = 240 minutes. The question asks for hours, so the answer is 4."),
    dict(id="E12", category="easy_lookup", question="What is the most common incident description?",
         sql="SELECT i.short_desc, COUNT(*) AS incidents FROM incidents i "
             "GROUP BY i.short_desc ORDER BY incidents DESC, i.short_desc LIMIT 1",
         notes="Top recurring issue by count of short_desc. No tie at the top in either seed size."),

    # ---------------- date ranges ----------------
    dict(id="D05", category="date_range", question="How many incidents were opened this month?",
         sql=f"SELECT COUNT(*) AS incidents FROM incidents i WHERE {THIS_MONTH}",
         notes="This month = September 2026 up to the as-of date 2026-09-28 (glossary 'this month')."),
    dict(id="D06", category="date_range", question="How many incidents were opened per month?",
         sql="SELECT strftime('%Y-%m', i.opened_at) AS month, COUNT(*) AS incidents FROM incidents i "
             "GROUP BY month ORDER BY month",
         alternatives=[dict(reading="month number only ('04'..'09')",
                            sql="SELECT strftime('%m', i.opened_at) AS month, COUNT(*) AS incidents "
                                "FROM incidents i GROUP BY month ORDER BY month")],
         notes="Monthly intake trend, April to September 2026. Month labelled 'YYYY-MM' (or 'MM'); any "
               "other label format is a wrong result even if the counts are right."),
    dict(id="D07", category="date_range", question="How many high-risk changes are planned this month?",
         sql="SELECT COUNT(*) AS high_risk_changes FROM changes c WHERE c.risk = 'High' "
             "AND c.status <> 'Cancelled' "
             "AND c.planned_start >= '2026-09-01' AND c.planned_start < '2026-10-01'",
         ambiguous=True,
         alternatives=[dict(reading="cancelled changes included",
                            sql="SELECT COUNT(*) AS high_risk_changes FROM changes c WHERE c.risk = 'High' "
                                "AND c.planned_start >= '2026-09-01' AND c.planned_start < '2026-10-01'"),
                       dict(reading="this month up to the as-of date (glossary 'this month'), not cancelled",
                            sql="SELECT COUNT(*) AS high_risk_changes FROM changes c WHERE c.risk = 'High' "
                                "AND c.status <> 'Cancelled' "
                                "AND c.planned_start >= '2026-09-01' AND c.planned_start < '2026-09-28'")],
         notes="Changes have no opened_at: the time column is planned_start. 'Planned this month' most "
               "naturally covers the whole of September 2026, windows after the as-of date included, and a "
               "cancelled change is no longer planned; both the cancelled-included and the glossary "
               "up-to-as-of readings are also accepted. All give 3 at the default size but differ on the "
               "large set."),
    dict(id="D08", category="date_range", question="How many incidents were resolved this month?",
         sql=f"SELECT COUNT(*) AS incidents FROM incidents i WHERE {FINISHED} "
             f"AND i.resolved_at >= '2026-09-01' AND i.resolved_at < '2026-09-28'",
         notes="'Resolved this month' filters resolved_at (glossary 'resolved incident'), not opened_at."),
    dict(id="D09", category="date_range",
         question="What was the mean time to resolve for incidents opened last month?",
         sql=f"SELECT {MTTR} AS mttr_minutes FROM incidents i WHERE {FINISHED} AND {LAST_MONTH}",
         tolerance=0.5,
         alternatives=[dict(reading="in hours",
                            sql=f"SELECT {MTTR} / 60.0 AS mttr_hours FROM incidents i "
                                f"WHERE {FINISHED} AND {LAST_MONTH}")],
         notes="Metric mttr over resolved or closed incidents opened in August 2026, in minutes "
               "(hours also accepted)."),
    dict(id="D10", category="date_range", question="How many upcoming changes are there?",
         sql="SELECT COUNT(*) AS upcoming_changes FROM changes c "
             "WHERE c.planned_start >= '2026-09-28' AND c.status <> 'Cancelled'",
         notes="Glossary 'upcoming change': planned_start on or after the as-of date and not cancelled "
               "(10 at the default size, all in the next 28 days)."),
    dict(id="D11", category="date_range",
         question="How many high-risk changes are scheduled next week, per team?",
         sql="SELECT g.name AS team, COUNT(c.id) AS high_risk_changes FROM assignment_groups g "
             "LEFT JOIN changes c ON c.assignment_group_id = g.id AND c.risk = 'High' "
             "AND c.status <> 'Cancelled' "
             "AND c.planned_start >= '2026-10-05' AND c.planned_start < '2026-10-12' "
             "GROUP BY g.name ORDER BY g.name",
         ambiguous=True,
         alternatives=[dict(reading="next 7 days / the as-of week (2026-09-28 to 2026-10-04)",
                            sql="SELECT g.name AS team, COUNT(c.id) AS high_risk_changes "
                                "FROM assignment_groups g "
                                "LEFT JOIN changes c ON c.assignment_group_id = g.id AND c.risk = 'High' "
                                "AND c.status <> 'Cancelled' "
                                "AND c.planned_start >= '2026-09-28' AND c.planned_start < '2026-10-05' "
                                "GROUP BY g.name ORDER BY g.name")],
         notes="Schema example question 5. Unlike D02 the two readings of 'next week' give different rows: "
               "the pinned changes 91 (Network, as-of week) and 92 (Service Desk, following week) belong "
               "to different teams. Teams with zero changes must still be listed (LEFT JOIN)."),
    dict(id="D12", category="date_range", question="How many P1 incidents were opened last week?",
         sql="SELECT COUNT(*) AS p1_incidents FROM incidents i WHERE i.priority = 1 "
             "AND i.opened_at >= '2026-09-21' AND i.opened_at < '2026-09-28'",
         notes="Last week = Monday 2026-09-21 to Sunday 2026-09-27, on opened_at. Small number (1) so a "
               "wrong window is easy to spot."),
    dict(id="D13", category="date_range", question="How many incidents were opened in August 2026?",
         sql=f"SELECT COUNT(*) AS incidents FROM incidents i WHERE {LAST_MONTH}",
         notes="Explicit month instead of a relative phrase; must equal D01."),

    # ---------------- multi-table joins ----------------
    dict(id="J05", category="multi_table_join",
         question="What is the average resolution time by priority?",
         sql=f"SELECT i.priority, {MTTR} AS mttr_minutes FROM incidents i WHERE {FINISHED} "
             f"GROUP BY i.priority ORDER BY i.priority",
         tolerance=0.5,
         alternatives=[dict(reading="in hours",
                            sql=f"SELECT i.priority, {MTTR} / 60.0 AS mttr_hours FROM incidents i "
                                f"WHERE {FINISHED} GROUP BY i.priority ORDER BY i.priority")],
         notes="Schema example question 3: metric mttr per priority, resolved or closed only, in minutes "
               "(hours also accepted)."),
    dict(id="J06", category="multi_table_join", question="Which team has the highest SLA breach rate?",
         sql=f"SELECT g.name AS team FROM incidents i JOIN sla_targets s ON s.priority = i.priority "
             f"JOIN assignment_groups g ON g.id = i.assignment_group_id WHERE {FINISHED} "
             f"GROUP BY g.name ORDER BY AVG(CASE WHEN {BREACHED} THEN 1.0 ELSE 0.0 END) DESC, g.name "
             f"LIMIT 1",
         notes="Rate, not count. At the default size Database (23.3%) beats Network (22.1%) although Network "
               "has more breaches (17 vs 14). Only the team name is compared, so the rate may be shown in "
               "any format."),
    dict(id="J07", category="multi_table_join",
         question="How many agents does each assignment group have?",
         sql="SELECT g.name AS team, COUNT(u.id) AS agents FROM assignment_groups g "
             "LEFT JOIN users u ON u.assignment_group_id = g.id AND u.role = 'agent' "
             "GROUP BY g.name ORDER BY g.name",
         notes="Schema example question 6. Agents only: team leads are excluded (11/5/5/5/5)."),
    dict(id="J08", category="multi_table_join", question="What is the SLA breach rate per team?",
         sql=f"SELECT g.name AS team, {BREACH_PCT} AS breach_pct FROM incidents i "
             f"JOIN sla_targets s ON s.priority = i.priority "
             f"JOIN assignment_groups g ON g.id = i.assignment_group_id WHERE {FINISHED} "
             f"GROUP BY g.name ORDER BY g.name",
         tolerance=0.1,
         notes="Percentage of resolved or closed incidents per team, all time (metric sla_breach_rate)."),
    dict(id="J09", category="multi_table_join", question="What is the reopen rate per team?",
         sql="SELECT g.name AS team, "
             "ROUND(100.0 * AVG(CASE WHEN i.reopened_count > 0 THEN 1.0 ELSE 0.0 END), 1) AS reopen_pct "
             "FROM incidents i JOIN assignment_groups g ON g.id = i.assignment_group_id "
             "GROUP BY g.name ORDER BY g.name",
         tolerance=0.1,
         notes="Metric reopen_rate as a percentage; the denominator is all incidents of the team."),
    dict(id="J10", category="multi_table_join",
         question="Which priority has the longest average resolution time?",
         sql=f"SELECT i.priority FROM incidents i WHERE {FINISHED} GROUP BY i.priority "
             f"ORDER BY {MTTR} DESC LIMIT 1",
         notes="Priority 4 (Low): the 5-day target lets tickets run longest. Only the priority is compared."),
    dict(id="J11", category="multi_table_join", question="How many overdue incidents does each team have?",
         sql=f"SELECT g.name AS team, SUM(CASE WHEN {OVERDUE} THEN 1 ELSE 0 END) AS overdue "
             f"FROM assignment_groups g LEFT JOIN incidents i ON i.assignment_group_id = g.id "
             f"LEFT JOIN sla_targets s ON s.priority = i.priority GROUP BY g.name ORDER BY g.name",
         notes="Glossary 'overdue': open (New, In Progress, On Hold) and already past its SLA target as of "
               "2026-09-28. Not the same as SLA breach, which counts resolved incidents."),
    dict(id="J12", category="multi_table_join", question="How many upcoming changes does each team have?",
         sql="SELECT g.name AS team, COUNT(c.id) AS upcoming_changes FROM assignment_groups g "
             "LEFT JOIN changes c ON c.assignment_group_id = g.id "
             "AND c.planned_start >= '2026-09-28' AND c.status <> 'Cancelled' "
             "GROUP BY g.name ORDER BY g.name",
         notes="Per-team version of D10; teams with no upcoming change must show 0."),
    dict(id="J13", category="multi_table_join",
         question="How many incidents did the Service Desk resolve within SLA last month?",
         sql=f"SELECT COUNT(*) AS within_sla FROM incidents i JOIN sla_targets s ON s.priority = i.priority "
             f"JOIN assignment_groups g ON g.id = i.assignment_group_id "
             f"WHERE g.name = 'Service Desk' AND {FINISHED} "
             f"AND i.resolved_at >= '2026-08-01' AND i.resolved_at < '2026-09-01' "
             f"AND {MINUTES} <= s.target_minutes",
         ambiguous=True,
         alternatives=[dict(reading="opened last month (the breach metric's default time column)",
                            sql=f"SELECT COUNT(*) AS within_sla FROM incidents i "
                                f"JOIN sla_targets s ON s.priority = i.priority "
                                f"JOIN assignment_groups g ON g.id = i.assignment_group_id "
                                f"WHERE g.name = 'Service Desk' AND {FINISHED} AND {LAST_MONTH} "
                                f"AND {MINUTES} <= s.target_minutes")],
         notes="The complement of a breach: resolution minutes <= target. 'Resolved last month' filters "
               "resolved_at (glossary 'resolved incident', as in D04): 20 at the default size. Filtering "
               "opened_at instead (the SLA-breach convention, 19) is also accepted."),
    dict(id="J14", category="multi_table_join", question="How many users are in each team?",
         sql="SELECT g.name AS team, COUNT(u.id) AS users FROM assignment_groups g "
             "LEFT JOIN users u ON u.assignment_group_id = g.id GROUP BY g.name ORDER BY g.name",
         notes="Agents plus team leads (12/6/6/6/6). Managers and the admin have no team and are not "
               "listed under any group. Must not reveal names."),

    # ---------------- known edge cases ----------------
    dict(id="K04", category="edge_case", question="How many cancelled P1 incidents are there?",
         sql="SELECT COUNT(*) AS cancelled_p1 FROM incidents i "
             "WHERE i.priority = 1 AND i.status = 'Cancelled'",
         notes="At the default size the answer is 0 (only P3 and P4 incidents are cancelled): an empty "
               "result or an error is a failure, not a zero."),
    dict(id="K05", category="edge_case", question="How many incidents does the Security team have?",
         sql="SELECT COUNT(i.id) AS incidents FROM incidents i "
             "JOIN assignment_groups g ON g.id = i.assignment_group_id WHERE g.name = 'Security'",
         alternatives=[dict(reading="no such team, so no row",
                            sql="SELECT g.name AS team, COUNT(i.id) AS incidents FROM incidents i "
                                "JOIN assignment_groups g ON g.id = i.assignment_group_id "
                                "WHERE g.name = 'Security' GROUP BY g.name")],
         notes="There is no Security team. Both 0 and an empty result pass; inventing a team or an "
               "SQL error fails. Not worded 'assigned to the Security team': 'assigned to' is a synonym of "
               "the unanswerable term 'assignee', so the agent refuses before calling the model."),
    dict(id="K06", category="edge_case", question="How many incidents were opened in 2025?",
         sql="SELECT COUNT(*) AS incidents FROM incidents i "
             "WHERE i.opened_at >= '2025-01-01' AND i.opened_at < '2026-01-01'",
         notes="The data starts in April 2026, so the answer is 0, not an error."),
    dict(id="K07", category="edge_case", question="Which teams have no open P1 incidents?",
         sql=f"SELECT g.name AS team FROM assignment_groups g "
             f"LEFT JOIN incidents i ON i.assignment_group_id = g.id AND i.priority = 1 AND {OPEN} "
             f"GROUP BY g.name HAVING COUNT(i.id) = 0 ORDER BY g.name",
         notes="Zero-count group. At the default size only Service Desk has an open P1, so four teams are "
               "listed and an inner join returns nothing. On the large set every team has one, so the "
               "correct answer is no rows."),
    dict(id="K08", category="edge_case",
         question="How many incidents opened last month are still open?",
         sql=f"SELECT COUNT(*) AS still_open FROM incidents i WHERE {LAST_MONTH} AND {OPEN}",
         notes="Two filters: opened in August 2026 and status open. The answer is 0 at the default size "
               "(all August incidents are finished or cancelled)."),
    dict(id="K09", category="edge_case", question="What is the overall reopen rate?",
         sql="SELECT ROUND(100.0 * AVG(CASE WHEN i.reopened_count > 0 THEN 1.0 ELSE 0.0 END), 1) "
             "AS reopen_pct FROM incidents i",
         tolerance=0.05,
         alternatives=[dict(reading="ratio 0-1",
                            sql="SELECT ROUND(AVG(CASE WHEN i.reopened_count > 0 THEN 1.0 ELSE 0.0 END), 3) "
                                "AS reopen_rate FROM incidents i")],
         notes="Metric reopen_rate over all 500 incidents: 44/500 = 8.8% (0.088 also accepted)."),
    dict(id="K10", category="edge_case", question="Which incident took the longest to resolve?",
         sql=f"SELECT i.id FROM incidents i WHERE {FINISHED} ORDER BY {MINUTES} DESC, i.id LIMIT 1",
         notes="Resolved or closed only (open incidents have no resolved_at). Only the id is compared."),
    dict(id="K11", category="edge_case",
         question="What was the response time for P1 incidents last month?",
         refusal=True,
         notes="Not answerable: response time is not stored (glossary 'response time', is_answerable = 0). "
               "Pass = the answer says so; it must not return resolution time as if it were response time."),
    dict(id="K12", category="edge_case", question="How many incidents are assigned to the Network team?",
         sql="SELECT COUNT(i.id) AS incidents FROM incidents i "
             "JOIN assignment_groups g ON g.id = i.assignment_group_id WHERE g.name = 'Network'",
         notes="Regression for a false refusal (2026-09-30): 'assigned to' used to be a synonym of the "
               "unanswerable term 'assignee', so this team question was refused before any model call. "
               "'Assigned to <team>' is a plain per-team count (all statuses)."),
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
