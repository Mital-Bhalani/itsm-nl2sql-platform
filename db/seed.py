"""
Build db/tickets.sqlite from db/schema.sql and fill it with synthetic ITSM data.

    python db/seed.py                                    # default sample: 500 / 100
    python db/seed.py --incidents 50000 --changes 10000 --out db/tickets_large.sqlite

The output is deterministic: one seeded random generator and a fixed anchor date
(NOW), so every run with the same arguments produces exactly the same rows.

What gets generated (defaults in brackets):
    5 assignment groups, 40 users, 4 SLA targets,
    N incidents [500] over the 180 days before NOW: 88% resolved/closed, 2% cancelled,
        the rest still open,
    M changes [100]: 90% in the past 180 days, 10% scheduled in the next 28 days.
Counts scale with N and M; the ratios, users and reference data do not.
Each incident also carries an impact, the assignee and first response (unless New), the
caller (NULL when monitoring raised it), an escalation time for some, downtime once finished,
and for some a link to the team's most recent change; started changes carry actual times.

Exactly 15% of resolved/closed incidents breach their SLA target, measured as
wall-clock minutes from opened_at to resolved_at (see the schema.sql header).
Breaches are weighted toward Network and Database so groups differ.

The columns added on 2026-10-02 (assignee, caller, first response, impact, downtime,
escalation, change link; actual change window; response target) are filled by a SECOND
generator (EXTRA_SEED) in a pass after the original rows exist, so every value the original
columns held before that date is unchanged at any size.
"""

import argparse
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = DB_DIR / "schema.sql"
DB_PATH = DB_DIR / "tickets.sqlite"

SEED = 42
NOW = datetime(2026, 9, 28, 0, 0, 0)  # fixed anchor, UTC
WINDOW_START = NOW - timedelta(days=180)
TS_FORMAT = "%Y-%m-%d %H:%M:%S"

N_INCIDENTS = 500      # default; --incidents
RESOLVED_SHARE = 0.88  # Resolved or Closed
CANCELLED_SHARE = 0.02
BREACH_RATE = 0.15     # of resolved/closed incidents, exact

N_CHANGES = 100        # default; --changes
PAST_CHANGE_SHARE = 0.90

# The first two future changes are pinned to High risk so "high-risk changes next week"
# (eval question 5) has data under both readings of "next week": the as-of week and the
# following calendar week. Applied after generation, with no extra random draws, so every
# other row is unchanged. planned_start per pinned change (4-hour window, status Scheduled):
PINNED_HIGH_RISK_STARTS = [
    datetime(2026, 10, 1, 21, 0, 0),  # Thursday of the as-of week
    datetime(2026, 10, 7, 21, 0, 0),  # Wednesday of the following calendar week
]

rng = random.Random(SEED)

# Second generator for the columns added on 2026-10-02. Its draws never touch `rng`, so the
# original columns keep their historical values.
EXTRA_SEED = 43
extra = random.Random(EXTRA_SEED)

# -----------------------------------------------------------------------------
#  Reference data
# -----------------------------------------------------------------------------
# priority -> target minutes (P1 4h, P2 8h, P3 2d, P4 5d)
SLA_TARGETS = {1: 240, 2: 480, 3: 2880, 4: 7200}
# priority -> first-response target minutes (P1 30 min, P2 1 h, P3 4 h, P4 8 h)
RESPONSE_TARGETS = {1: 30, 2: 60, 3: 240, 4: 480}
PRIORITY_WEIGHTS = {1: 5, 2: 15, 3: 50, 4: 30}

# --- the 2026-10-02 columns ---------------------------------------------------
# impact (1 High, 2 Medium, 3 Low) is drawn per priority: urgent incidents usually hit more
# people, but the two are not the same thing.
IMPACT_WEIGHTS = {
    1: {1: 70, 2: 25, 3: 5},
    2: {1: 30, 2: 50, 3: 20},
    3: {1: 5, 2: 40, 3: 55},
    4: {1: 1, 2: 19, 3: 80},
}
RESPONSE_LATE_SHARE = 0.10          # share of first responses that miss response_minutes
LEAD_ASSIGNEE_SHARE = 0.15          # share of assignments that go to the team lead
CANCELLED_ASSIGNED_SHARE = 0.50     # cancelled incidents that had been picked up first
MONITORING_CALLER_SHARE = {1: 0.03, 2: 0.30, 3: 0.25, 4: 0.10, 5: 0.35}  # caller_id NULL
OUTAGE_SHARE = {1: 0.80, 2: 0.40, 3: 0.10, 4: 0.0}   # finished incidents with downtime > 0
ESCALATION_SHARE = {1: 0.50, 2: 0.25, 3: 0.08, 4: 0.03}
ESCALATION_BREACH_BONUS = 0.25     # added when the incident breached its SLA
CHANGE_CAUSED_SHARE = 0.15          # incidents that may be linked to the team's most recent change
CHANGE_CAUSE_WINDOW_DAYS = 14       #   if one started up to this many days before opened_at
ACTUAL_START_JITTER_MIN = 30        # actual_start within +/- this many minutes of planned
OVERRUN_SHARE = 0.20                # finished changes whose actual_end passes planned_end

# id -> name
GROUPS = {
    1: "Service Desk",
    2: "Network",
    3: "Database",
    4: "Application Support",
    5: "Infrastructure",
}
INCIDENT_GROUP_WEIGHTS = {1: 35, 2: 16, 3: 14, 4: 20, 5: 15}
CHANGE_GROUP_WEIGHTS = {1: 5, 2: 25, 3: 20, 4: 20, 5: 30}
# Relative likelihood that a resolved incident in this group is picked to breach.
BREACH_GROUP_WEIGHTS = {1: 0.6, 2: 2.0, 3: 1.8, 4: 1.0, 5: 1.0}

# Agents per group (31 in total); every group also gets one team lead.
AGENTS_PER_GROUP = {1: 11, 2: 5, 3: 5, 4: 5, 5: 5}
N_MANAGERS = 3
N_ADMINS = 1

FIRST_NAMES = [
    "Aisha", "Ben", "Carla", "Dev", "Elena", "Farid", "Grace", "Hiro",
    "Isla", "Jonas", "Kavya", "Liam", "Maya", "Noah", "Olu", "Priya",
    "Quinn", "Ravi", "Sofia", "Tom",
]
LAST_NAMES = [
    "Adams", "Bose", "Chen", "Dubois", "Evans", "Fischer", "Garcia", "Hughes",
    "Iyer", "Jensen", "Kowalski", "Lopez", "Mehta", "Nakamura", "Okafor",
    "Patel", "Rossi", "Silva", "Turner", "Weber",
]

INCIDENT_DESCRIPTIONS = {
    1: [
        "User locked out of account after password expiry",
        "Laptop will not boot past manufacturer logo",
        "Outlook not syncing new mail",
        "Unable to connect to office printer",
        "MFA prompt not received on mobile",
        "New starter missing access to shared drive",
        "Teams calls dropping after a few minutes",
        "Monitor flickering on docking station",
    ],
    2: [
        "VPN tunnel dropping for remote users",
        "Wi-Fi unavailable on floor 3",
        "High packet loss between data centres",
        "Branch office site-to-site link down",
        "DNS resolution failing for internal domains",
        "Firewall blocking payroll application traffic",
        "Load balancer health checks failing",
        "Slow network performance in London office",
    ],
    3: [
        "Nightly backup job failed on finance database",
        "Replication lag on reporting replica",
        "Deadlocks in order management database",
        "Database storage above 90 percent",
        "Slow queries on customer search",
        "Failed login attempts locking service account",
        "Index rebuild job overran maintenance window",
        "Connection pool exhausted on CRM database",
    ],
    4: [
        "Checkout page returning HTTP 500 errors",
        "CRM export to CSV timing out",
        "HR portal showing wrong leave balance",
        "Mobile app crashing on login",
        "Invoice PDF generation failing",
        "Single sign-on redirect loop in intranet",
        "Search results missing recent documents",
        "Scheduled report emails not sent",
    ],
    5: [
        "Disk full on application server",
        "VM unresponsive after host patching",
        "Certificate expired on internal web server",
        "Backup agent offline on file server",
        "High CPU on virtualisation cluster",
        "Cloud storage bucket access denied",
        "Kubernetes pod restarting in a loop",
        "Server room temperature alert",
    ],
}

CHANGE_DESCRIPTIONS = {
    1: [
        "Roll out new laptop image to service desk build process",
        "Update self-service password reset portal",
        "Migrate shared mailboxes to new licence tier",
    ],
    2: [
        "Upgrade core switch firmware",
        "Replace edge firewall rule base",
        "Add new VLAN for meeting room devices",
        "Migrate VPN concentrator to new appliance",
        "Increase WAN bandwidth for branch offices",
    ],
    3: [
        "Apply quarterly database engine patch",
        "Add index to orders table",
        "Migrate reporting database to new storage",
        "Rotate database service account credentials",
        "Enable point-in-time recovery on finance database",
    ],
    4: [
        "Deploy CRM release 4.2",
        "Upgrade HR portal framework version",
        "Enable new checkout payment provider",
        "Deploy mobile app API hotfix",
        "Change single sign-on identity provider settings",
    ],
    5: [
        "Monthly OS patching for Windows servers",
        "Expand storage on virtualisation cluster",
        "Renew and replace internal TLS certificates",
        "Upgrade Kubernetes cluster version",
        "Decommission legacy file server",
    ],
}

RISK_WEIGHTS = {"Low": 50, "Moderate": 35, "High": 15}
# (min, max) planned duration in minutes per risk level
CHANGE_DURATION = {"Low": (30, 120), "Moderate": (60, 240), "High": (120, 480)}


# -----------------------------------------------------------------------------
#  Helpers
# -----------------------------------------------------------------------------
def weighted(weights):
    """Pick one key from a {key: weight} dict."""
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def ts(moment):
    return moment.strftime(TS_FORMAT)


def random_moment(start, end, business_prob):
    """
    A random moment in [start, end). With probability business_prob it is moved
    to a weekday between 08:00 and 18:00 (on the same day or the Friday before).
    """
    span = (end - start).total_seconds()
    moment = start + timedelta(seconds=int(rng.uniform(0, span)))
    if rng.random() < business_prob:
        while moment.weekday() >= 5:  # Saturday / Sunday
            moment -= timedelta(days=1)
        moment = moment.replace(
            hour=rng.randint(8, 17), minute=rng.randint(0, 59), second=rng.randint(0, 59)
        )
    return min(max(moment, start), end - timedelta(seconds=1))


def maintenance_moment(start, end):
    """
    A random start time in [start, end), biased toward maintenance windows:
    70% weekday evenings (20:00-23:00) or weekends, 30% business hours.
    """
    span = (end - start).total_seconds()
    moment = start + timedelta(seconds=int(rng.uniform(0, span)))
    if rng.random() < 0.7:
        hour = rng.randint(20, 23) if moment.weekday() < 5 else rng.randint(6, 22)
    else:
        hour = rng.randint(9, 16)
    moment = moment.replace(hour=hour, minute=rng.choice([0, 15, 30, 45]), second=0)
    return min(max(moment, start), end - timedelta(minutes=1))


def weighted_sample(items, weight_of, k):
    """Pick k distinct items, each with probability proportional to weight_of(item)."""
    keyed = [(rng.random() ** (1.0 / weight_of(item)), item) for item in items]
    keyed.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in keyed[:k]]


# -----------------------------------------------------------------------------
#  Row generators
# -----------------------------------------------------------------------------
def make_users():
    names = rng.sample([f"{f} {l}" for f in FIRST_NAMES for l in LAST_NAMES], 40)
    slots = []
    for group_id in GROUPS:
        slots.append(("team_lead", group_id))
        slots.extend(("agent", group_id) for _ in range(AGENTS_PER_GROUP[group_id]))
    slots.extend(("manager", None) for _ in range(N_MANAGERS))
    slots.extend(("admin", None) for _ in range(N_ADMINS))
    return [
        (user_id, name, role, group_id)
        for user_id, (name, (role, group_id)) in enumerate(zip(names, slots), start=1)
    ]


def make_incidents(n_incidents):
    # Fix the status bucket of every incident first so the counts are exact.
    n_resolved = round(RESOLVED_SHARE * n_incidents)
    n_cancelled = round(CANCELLED_SHARE * n_incidents)
    n_open = n_incidents - n_resolved - n_cancelled  # New / In Progress / On Hold
    buckets = ["resolved"] * n_resolved + ["cancelled"] * n_cancelled + ["open"] * n_open
    rng.shuffle(buckets)

    drafts = []
    for incident_id, bucket in enumerate(buckets, start=1):
        group_id = weighted(INCIDENT_GROUP_WEIGHTS)
        drafts.append({
            "id": incident_id,
            "bucket": bucket,
            "priority": weighted(PRIORITY_WEIGHTS),
            "group_id": group_id,
            "short_desc": rng.choice(INCIDENT_DESCRIPTIONS[group_id]),
        })

    resolved = [d for d in drafts if d["bucket"] == "resolved"]
    n_breach = round(BREACH_RATE * len(resolved))
    breach_ids = {
        d["id"]
        for d in weighted_sample(resolved, lambda d: BREACH_GROUP_WEIGHTS[d["group_id"]], n_breach)
    }

    rows = []
    for d in drafts:
        target = SLA_TARGETS[d["priority"]]
        breached = d["id"] in breach_ids
        resolved_at = None

        if d["bucket"] == "open":
            opened_at = random_moment(NOW - timedelta(days=14), NOW, 0.75)
            status = rng.choices(["New", "In Progress", "On Hold"], weights=[25, 55, 20])[0]
        elif d["bucket"] == "cancelled":
            opened_at = random_moment(WINDOW_START, NOW, 0.75)
            status = "Cancelled"
        else:
            fraction = rng.uniform(1.05, 3.0) if breached else rng.uniform(0.10, 0.95)
            duration = timedelta(minutes=target * fraction)
            opened_at = random_moment(WINDOW_START, NOW, 0.75)
            if opened_at + duration > NOW:  # resolution must not be in the future
                opened_at = NOW - duration - timedelta(minutes=rng.randint(10, 600))
            resolved_at = opened_at + duration
            status = "Closed" if resolved_at < NOW - timedelta(days=5) else "Resolved"

        if d["bucket"] == "resolved":
            reopen_weights = [75, 18, 7] if breached else [91, 7, 2]
            reopened_count = rng.choices([0, 1, 2], weights=reopen_weights)[0]
        else:
            reopened_count = 0

        rows.append((
            d["id"],
            d["short_desc"],
            d["priority"],
            status,
            d["group_id"],
            ts(opened_at),
            ts(resolved_at) if resolved_at else None,
            reopened_count,
        ))
    return rows


def make_changes(n_changes):
    n_past = round(PAST_CHANGE_SHARE * n_changes)
    rows = []
    for change_id in range(1, n_changes + 1):
        is_future = change_id > n_past
        group_id = weighted(CHANGE_GROUP_WEIGHTS)
        risk = weighted(RISK_WEIGHTS)
        low, high = CHANGE_DURATION[risk]
        duration = timedelta(minutes=rng.randint(low // 15, high // 15) * 15)

        if is_future:
            start = maintenance_moment(NOW, NOW + timedelta(days=28))
            if start < NOW + timedelta(days=7):
                status = "Scheduled"
            else:
                status = rng.choices(["Draft", "Assess", "Scheduled"], weights=[30, 40, 30])[0]
        else:
            start = maintenance_moment(WINDOW_START, NOW)
            end = start + duration
            if end > NOW:
                status = "Implement"
            elif end > NOW - timedelta(days=3):
                status = "Review"
            else:
                status = rng.choices(["Closed", "Cancelled"], weights=[90, 10])[0]

        rows.append((
            change_id,
            rng.choice(CHANGE_DESCRIPTIONS[group_id]),
            risk,
            status,
            group_id,
            ts(start),
            ts(start + duration),
        ))

    for offset, start in enumerate(PINNED_HIGH_RISK_STARTS, start=1):
        change_id = n_past + offset  # the first future changes (91 and 92 at the default size)
        _, description, _, _, group_id, _, _ = rows[change_id - 1]
        rows[change_id - 1] = (
            change_id, description, "High", "Scheduled", group_id,
            ts(start), ts(start + timedelta(hours=4)),
        )
    return rows


# -----------------------------------------------------------------------------
#  Columns added 2026-10-02 (second generator; original columns untouched)
# -----------------------------------------------------------------------------
def parse_ts(text):
    return datetime.strptime(text, TS_FORMAT)


def enrich_changes(changes):
    """
    Append actual_start and actual_end to every change row. Set for changes that have started
    (Implement: start only; Review and Closed: both); about OVERRUN_SHARE of the finished ones
    end after their planned window.
    """
    out = []
    for row in changes:
        change_id, description, risk, status, group_id, planned_start, planned_end = row
        actual_start = actual_end = None
        if status in ("Implement", "Review", "Closed"):
            start = parse_ts(planned_start) + timedelta(
                minutes=extra.randint(-ACTUAL_START_JITTER_MIN // 5, ACTUAL_START_JITTER_MIN // 5) * 5)
            start = min(start, NOW - timedelta(minutes=1))
            actual_start = ts(start)
            if status != "Implement":
                planned = parse_ts(planned_end) - parse_ts(planned_start)
                if extra.random() < OVERRUN_SHARE:
                    end = parse_ts(planned_end) + timedelta(
                        minutes=max(5, round(planned.total_seconds() / 60 * extra.uniform(0.05, 0.8) / 5) * 5))
                else:  # finished inside the booked window, even after a late start
                    end = start + timedelta(
                        minutes=max(5, round(planned.total_seconds() / 60 * extra.uniform(0.5, 0.95) / 5) * 5))
                    end = min(end, parse_ts(planned_end))
                actual_end = ts(min(max(end, start), NOW - timedelta(minutes=1)))
        out.append(row + (actual_start, actual_end))
    return out


def enrich_incidents(incidents, users, changes):
    """
    Append impact, assignee_id, caller_id, responded_at, escalated_at, downtime_minutes and
    caused_by_change_id to every incident row (see the schema.sql header for the rules).
    """
    team_staff = {}
    for user_id, _, role, group_id in users:
        if group_id is not None:
            team_staff.setdefault(group_id, {"agent": [], "team_lead": []})[role].append(user_id)
    all_users = [user_id for user_id, *_ in users]
    started_changes = [(c[0], c[4], parse_ts(c[5])) for c in changes
                       if c[3] in ("Implement", "Review", "Closed")]

    out = []
    for row in incidents:
        incident_id, _, priority, status, group_id, opened_text, resolved_text, _ = row
        opened = parse_ts(opened_text)
        resolved = parse_ts(resolved_text) if resolved_text else None
        end = resolved or (NOW - timedelta(seconds=1))
        finished = status in ("Resolved", "Closed")
        is_open = status in ("New", "In Progress", "On Hold")

        impact = weighted_with(extra, IMPACT_WEIGHTS[priority])

        assignee_id = responded_at = None
        picked_up = status != "New" and (status != "Cancelled" or extra.random() < CANCELLED_ASSIGNED_SHARE)
        if picked_up:
            staff = team_staff[group_id]
            pool = staff["team_lead"] if extra.random() < LEAD_ASSIGNEE_SHARE else staff["agent"]
            assignee_id = extra.choice(pool)
            late = extra.random() < RESPONSE_LATE_SHARE
            fraction = extra.uniform(1.05, 3.0) if late else extra.uniform(0.05, 0.95)
            responded = opened + timedelta(minutes=RESPONSE_TARGETS[priority] * fraction)
            responded_at = ts(min(responded, end))

        caller_id = None if extra.random() < MONITORING_CALLER_SHARE[group_id] else extra.choice(all_users)

        escalated_at = None
        if picked_up:
            breached = finished and (resolved - opened).total_seconds() / 60 > SLA_TARGETS[priority]
            share = ESCALATION_SHARE[priority] + (ESCALATION_BREACH_BONUS if breached else 0.0)
            if extra.random() < share:
                escalated_at = ts(opened + (end - opened) * extra.uniform(0.2, 0.9))

        if is_open:
            downtime_minutes = None
        elif finished and extra.random() < OUTAGE_SHARE[priority]:
            resolution_minutes = (resolved - opened).total_seconds() / 60
            downtime_minutes = max(1, int(resolution_minutes * extra.uniform(0.2, 1.0)))
        else:
            downtime_minutes = 0

        caused_by_change_id = None
        if extra.random() < CHANGE_CAUSED_SHARE:
            # the team's most recent change that started shortly before the incident, if any
            candidates = [(cstart, cid) for cid, cgroup, cstart in started_changes
                          if cgroup == group_id
                          and cstart < opened <= cstart + timedelta(days=CHANGE_CAUSE_WINDOW_DAYS)]
            if candidates:
                caused_by_change_id = max(candidates)[1]

        out.append(row + (impact, assignee_id, caller_id, responded_at, escalated_at,
                          downtime_minutes, caused_by_change_id))
    return out


def weighted_with(generator, weights):
    """Pick one key from a {key: weight} dict with the given generator."""
    return generator.choices(list(weights), weights=list(weights.values()))[0]


# -----------------------------------------------------------------------------
#  Build
# -----------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Build the synthetic ITSM database.")
    parser.add_argument("--incidents", type=int, default=N_INCIDENTS,
                        help=f"number of incidents (default {N_INCIDENTS}, minimum 100)")
    parser.add_argument("--changes", type=int, default=N_CHANGES,
                        help=f"number of changes (default {N_CHANGES}, minimum 20)")
    parser.add_argument("--out", type=Path, default=DB_PATH,
                        help="database file to create (default db/tickets.sqlite)")
    args = parser.parse_args()
    if args.incidents < 100:
        parser.error("--incidents must be at least 100")
    if args.changes < 20:
        parser.error("--changes must be at least 20 (the two pinned High-risk changes need "
                     "future change ids)")
    return args


def main():
    args = parse_args()
    db_path = args.out.resolve()
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    # Generate in a fixed order so the random draws are always the same.
    users = make_users()
    incidents = make_incidents(args.incidents)
    changes = make_changes(args.changes)
    # Second pass with the second generator: changes first (incidents may link to them).
    changes = enrich_changes(changes)
    incidents = enrich_incidents(incidents, users, changes)

    with conn:
        conn.executemany("INSERT INTO assignment_groups VALUES (?, ?)", GROUPS.items())
        conn.executemany("INSERT INTO sla_targets VALUES (?, ?, ?)",
                         [(p, SLA_TARGETS[p], RESPONSE_TARGETS[p]) for p in SLA_TARGETS])
        conn.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", users)
        conn.executemany("INSERT INTO changes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", changes)
        conn.executemany("INSERT INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         incidents)

    print(f"Built {db_path.name}")
    for table in ["assignment_groups", "users", "sla_targets", "incidents", "changes"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<18} {count:>6}")

    breached, resolved = conn.execute("""
        SELECT SUM((julianday(i.resolved_at) - julianday(i.opened_at)) * 1440 > s.target_minutes),
               COUNT(*)
        FROM incidents i
        JOIN sla_targets s ON s.priority = i.priority
        WHERE i.status IN ('Resolved', 'Closed')
    """).fetchone()
    print(f"  SLA breach rate    {breached}/{resolved} = {breached / resolved:.1%}")

    late, responded = conn.execute("""
        SELECT SUM((julianday(i.responded_at) - julianday(i.opened_at)) * 1440 > s.response_minutes),
               COUNT(*)
        FROM incidents i
        JOIN sla_targets s ON s.priority = i.priority
        WHERE i.responded_at IS NOT NULL
    """).fetchone()
    facts = conn.execute("""
        SELECT SUM(assignee_id IS NULL), SUM(caller_id IS NULL), SUM(escalated_at IS NOT NULL),
               SUM(downtime_minutes > 0), SUM(caused_by_change_id IS NOT NULL)
        FROM incidents
    """).fetchone()
    overran, actual = conn.execute(
        "SELECT SUM(actual_end > planned_end), COUNT(actual_end) FROM changes").fetchone()
    print(f"  Response breaches  {late}/{responded} = {late / responded:.1%}")
    print(f"  Unassigned {facts[0]}, raised by monitoring {facts[1]}, escalated {facts[2]}, "
          f"with downtime {facts[3]}, caused by a change {facts[4]}")
    print(f"  Changes overran    {overran}/{actual} finished")

    conn.close()


if __name__ == "__main__":
    main()
