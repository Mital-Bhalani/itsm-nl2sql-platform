-- =============================================================================
--  ITSM ticket database — schema (SQLite 3.37+)
--
--  Five tables:
--    assignment_groups  teams that own work (Service Desk, Network, DBA, ...)
--    users              people, optionally belonging to one assignment group
--    sla_targets        resolution target per priority (P1..P4)
--    incidents          unplanned interruptions ("something is broken")
--    changes            planned modifications ("we are going to alter something")
--
--  Conventions:
--    * All timestamps are TEXT in ISO-8601 UTC, 'YYYY-MM-DD HH:MM:SS', so that
--      SQLite date functions (julianday, strftime, date) work on them directly.
--    * Priority is an INTEGER 1..4; lower is more urgent. Severity means the same:
--        1 = P1 / Sev1 / Critical, 2 = P2 / Sev2 / High,
--        3 = P3 / Sev3 / Medium,   4 = P4 / Sev4 / Low.
--    * Status / risk / role values are constrained with CHECK lists.
--    * SLA breach is NOT stored. It is derived:
--        (julianday(resolved_at) - julianday(opened_at)) * 1440 > target_minutes
--      measured in wall-clock minutes (no business hours or pause-on-hold).
--    * Tables are STRICT so SQLite enforces column types.
--    * Foreign keys are only enforced when each connection runs
--        PRAGMA foreign_keys = ON;
-- =============================================================================

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS changes;
DROP TABLE IF EXISTS incidents;
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
-- -----------------------------------------------------------------------------
CREATE TABLE sla_targets (
    priority        INTEGER PRIMARY KEY
                    CHECK (priority BETWEEN 1 AND 4),
    target_minutes  INTEGER NOT NULL
                    CHECK (target_minutes > 0)
) STRICT;

-- -----------------------------------------------------------------------------
--  incidents
--  resolved_at is set exactly when the incident is Resolved or Closed.
--  A reopen clears resolved_at and increments reopened_count.
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

    CHECK (resolved_at IS NULL OR resolved_at >= opened_at),
    CHECK ((status IN ('Resolved', 'Closed')) = (resolved_at IS NOT NULL))
) STRICT;

CREATE INDEX idx_incidents_group_opened ON incidents (assignment_group_id, opened_at);
CREATE INDEX idx_incidents_opened       ON incidents (opened_at);
CREATE INDEX idx_incidents_priority     ON incidents (priority);
CREATE INDEX idx_incidents_status       ON incidents (status);

-- -----------------------------------------------------------------------------
--  changes
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

    CHECK (planned_end >= planned_start)
) STRICT;

CREATE INDEX idx_changes_group_start ON changes (assignment_group_id, planned_start);
CREATE INDEX idx_changes_start       ON changes (planned_start);
CREATE INDEX idx_changes_status      ON changes (status);

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
-- =============================================================================
