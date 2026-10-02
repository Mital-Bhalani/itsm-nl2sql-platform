-- =============================================================================
--  ITSM ticket database — schema (SQLite 3.37+)
--
--  Five tables:
--    assignment_groups  teams that own work (Service Desk, Network, DBA, ...)
--    users              people, optionally belonging to one assignment group
--    sla_targets        resolution and first-response targets per priority (P1..P4)
--    changes            planned modifications ("we are going to alter something")
--    incidents          unplanned interruptions ("something is broken")
--
--  Conventions:
--    * All timestamps are TEXT in ISO-8601 UTC, 'YYYY-MM-DD HH:MM:SS', so that
--      SQLite date functions (julianday, strftime, date) work on them directly.
--    * Priority is an INTEGER 1..4; lower is more urgent. Severity means the same:
--        1 = P1 / Sev1 / Critical, 2 = P2 / Sev2 / High,
--        3 = P3 / Sev3 / Medium,   4 = P4 / Sev4 / Low.
--    * Impact is an INTEGER 1..3, separate from priority:
--        1 = High (whole site or many users), 2 = Medium (a department), 3 = Low (one user).
--    * Status / risk / role values are constrained with CHECK lists.
--    * SLA breach is NOT stored. It is derived:
--        (julianday(resolved_at) - julianday(opened_at)) * 1440 > target_minutes
--      measured in wall-clock minutes (no business hours or pause-on-hold).
--      Response breach is derived the same way from responded_at and response_minutes.
--    * Tables are STRICT so SQLite enforces column types.
--    * Foreign keys are only enforced when each connection runs
--        PRAGMA foreign_keys = ON;
--
--  Added 2026-10-02 (people, response, impact, downtime, escalation, change links):
--    incidents.assignee_id, caller_id, responded_at, impact, downtime_minutes,
--    escalated_at, caused_by_change_id; changes.actual_start, actual_end;
--    sla_targets.response_minutes. The columns that existed before are unchanged.
-- =============================================================================

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS incidents;
DROP TABLE IF EXISTS changes;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS sla_targets;
DROP TABLE IF EXISTS assignment_groups;

-- -----------------------------------------------------------------------------
--  assignment_groups
-- -----------------------------------------------------------------------------
CREATE TABLE assignment_groups (
    id    INTEGER PRIMARY KEY,
    name  TEXT    NOT NULL UNIQUE
) STRICT;

-- -----------------------------------------------------------------------------
--  users
--  assignment_group_id is nullable: managers and admins may not sit in a group.
--  Incidents point at users twice: assignee_id (who works it) and caller_id (who raised it).
-- -----------------------------------------------------------------------------
CREATE TABLE users (
    id                   INTEGER PRIMARY KEY,
    name                 TEXT    NOT NULL,
    role                 TEXT    NOT NULL
                         CHECK (role IN ('agent', 'team_lead', 'manager', 'admin')),
    assignment_group_id  INTEGER
                         REFERENCES assignment_groups (id)
) STRICT;

CREATE INDEX idx_users_group ON users (assignment_group_id);

-- -----------------------------------------------------------------------------
--  sla_targets
--  One row per priority; incidents.priority references this table.
--  target_minutes   = resolution target (opened_at -> resolved_at)
--  response_minutes = first-response target (opened_at -> responded_at)
-- -----------------------------------------------------------------------------
CREATE TABLE sla_targets (
    priority          INTEGER PRIMARY KEY
                      CHECK (priority BETWEEN 1 AND 4),
    target_minutes    INTEGER NOT NULL
                      CHECK (target_minutes > 0),
    response_minutes  INTEGER NOT NULL
                      CHECK (response_minutes > 0 AND response_minutes < target_minutes)
) STRICT;

-- -----------------------------------------------------------------------------
--  changes
--  planned_start/planned_end is the booked window; actual_start/actual_end is when the
--  work really ran: NULL until the change starts (Draft, Assess, Scheduled, Cancelled),
--  actual_end NULL while it is still running (Implement). actual_end > planned_end = overrun.
-- -----------------------------------------------------------------------------
CREATE TABLE changes (
    id                   INTEGER PRIMARY KEY,
    description          TEXT    NOT NULL,
    risk                 TEXT    NOT NULL
                         CHECK (risk IN ('Low', 'Moderate', 'High')),
    status               TEXT    NOT NULL
                         CHECK (status IN ('Draft', 'Assess', 'Scheduled',
                                           'Implement', 'Review', 'Closed',
                                           'Cancelled')),
    assignment_group_id  INTEGER NOT NULL
                         REFERENCES assignment_groups (id),
    planned_start        TEXT    NOT NULL,
    planned_end          TEXT    NOT NULL,
    actual_start         TEXT,
    actual_end           TEXT,

    CHECK (planned_end >= planned_start),
    CHECK (actual_end IS NULL OR actual_start IS NOT NULL),
    CHECK (actual_end IS NULL OR actual_end >= actual_start),
    CHECK ((status IN ('Implement', 'Review', 'Closed')) = (actual_start IS NOT NULL)),
    CHECK ((status IN ('Review', 'Closed')) = (actual_end IS NOT NULL))
) STRICT;

CREATE INDEX idx_changes_group_start ON changes (assignment_group_id, planned_start);
CREATE INDEX idx_changes_start       ON changes (planned_start);
CREATE INDEX idx_changes_status      ON changes (status);

-- -----------------------------------------------------------------------------
--  incidents
--  resolved_at is set exactly when the incident is Resolved or Closed.
--  A reopen clears resolved_at and increments reopened_count.
--  assignee_id and responded_at are set together: NULL while the incident is New
--  (nobody has picked it up), otherwise the agent or team lead of the owning team and the
--  moment they first responded. caller_id is NULL when monitoring raised the incident.
--  downtime_minutes is 0 when no service was down and NULL while the incident is still open
--  (not yet known). escalated_at is NULL unless the incident was escalated.
--  caused_by_change_id links an incident to the change that caused it (NULL = none known).
-- -----------------------------------------------------------------------------
CREATE TABLE incidents (
    id                   INTEGER PRIMARY KEY,
    short_desc           TEXT    NOT NULL,
    priority             INTEGER NOT NULL
                         REFERENCES sla_targets (priority),
    status               TEXT    NOT NULL
                         CHECK (status IN ('New', 'In Progress', 'On Hold',
                                           'Resolved', 'Closed', 'Cancelled')),
    assignment_group_id  INTEGER NOT NULL
                         REFERENCES assignment_groups (id),
    opened_at            TEXT    NOT NULL,
    resolved_at          TEXT,
    reopened_count       INTEGER NOT NULL DEFAULT 0
                         CHECK (reopened_count >= 0),
    impact               INTEGER NOT NULL
                         CHECK (impact BETWEEN 1 AND 3),
    assignee_id          INTEGER
                         REFERENCES users (id),
    caller_id            INTEGER
                         REFERENCES users (id),
    responded_at         TEXT,
    escalated_at         TEXT,
    downtime_minutes     INTEGER
                         CHECK (downtime_minutes >= 0),
    caused_by_change_id  INTEGER
                         REFERENCES changes (id),

    CHECK (resolved_at IS NULL OR resolved_at >= opened_at),
    CHECK ((status IN ('Resolved', 'Closed')) = (resolved_at IS NOT NULL)),
    CHECK ((assignee_id IS NULL) = (responded_at IS NULL)),
    CHECK (status <> 'New' OR assignee_id IS NULL),
    CHECK (responded_at IS NULL OR responded_at >= opened_at),
    CHECK (resolved_at IS NULL OR responded_at IS NULL OR responded_at <= resolved_at),
    CHECK (escalated_at IS NULL OR escalated_at >= opened_at),
    CHECK ((status IN ('New', 'In Progress', 'On Hold')) = (downtime_minutes IS NULL))
) STRICT;

CREATE INDEX idx_incidents_group_opened ON incidents (assignment_group_id, opened_at);
CREATE INDEX idx_incidents_opened       ON incidents (opened_at);
CREATE INDEX idx_incidents_priority     ON incidents (priority);
CREATE INDEX idx_incidents_status       ON incidents (status);
CREATE INDEX idx_incidents_assignee     ON incidents (assignee_id);
CREATE INDEX idx_incidents_caller       ON incidents (caller_id);
CREATE INDEX idx_incidents_change       ON incidents (caused_by_change_id);

-- =============================================================================
--  Example questions this schema should answer (seed for evals/)
--
--  1. Which assignment groups breached SLA most last month?
--     -> incidents JOIN sla_targets ON priority, JOIN assignment_groups,
--        compare resolution minutes to target_minutes.
--  2. How many P1 incidents are currently open?
--     -> priority = 1 AND status IN ('New', 'In Progress', 'On Hold').
--  3. What is the average resolution time by priority?
--  4. Which incidents were reopened more than once?
--  5. How many high-risk changes are scheduled next week, per group?
--  6. How many agents does each assignment group have?
--  7. Which agent resolved the most incidents?
--     -> GROUP BY assignee_id; report the user id and role, never users.name.
--  8. What is the average response time for P1 incidents?
--     -> minutes from opened_at to responded_at where responded_at is set.
--  9. How many incidents were caused by a change, and which change caused most?
--     -> caused_by_change_id IS NOT NULL, JOIN changes.
-- 10. How many changes overran their planned window?
--     -> actual_end > planned_end.
-- =============================================================================
