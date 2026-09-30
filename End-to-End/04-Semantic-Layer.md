# 4. Semantic layer (`semantics/`)

## Why it exists

The Day 1 spike (`agent/naive_spike.py`) sent a question to the AI with no context. The AI
invented a table called `sla_breaches`, used Postgres functions SQLite does not have, used the
real clock instead of the data's "today", and assumed a breach was stored as a column. The
semantic layer fixes this by storing the **meaning** of the data next to the data, in five
`meta_*` tables that the agent reads on every question.

## The one script: `build_catalog.py`

```bash
python semantics/build_catalog.py                          # into db/tickets.sqlite
python semantics/build_catalog.py --db db/tickets_large.sqlite
```

It reads `db/schema.sql` for the facts (types, keys, allowed values), combines them with the
hand-written descriptions kept in the script, writes the five tables, then **checks itself**
and exits with an error if anything is wrong.

## The five catalog tables

| Table | Rows | One row per | Key columns |
|---|---|---|---|
| `meta_tables` | 5 | data table | `description`, `grain` (what one row means) |
| `meta_columns` | 23 | column | `data_type`, `allowed_values`, `references_to`, `description`, `example_value`, `synonyms`, `is_pii`, `is_ambiguous` + `ambiguity_note` |
| `meta_joins` | 4 | foreign key | `cardinality`, `notes` (pitfalls, e.g. count with `COUNT(i.id)`) |
| `meta_metrics` | 3 | metric | `sql_expression`, `base_table`, `required_joins`, `filters`, `time_column`, `unit`, `notes` |
| `meta_glossary` | 51 | business term | `kind`, `synonyms`, `definition`, `sql_hint`, `is_answerable`, `is_ambiguous` |
| `meta_settings` | 3 | build setting | `as_of` (the date relative terms are anchored to), `dialect`, `built_at` |

### Metrics: formulas written once

| Metric | SQL expression | Filter |
|---|---|---|
| `mttr` (minutes) | `AVG((julianday(i.resolved_at) - julianday(i.opened_at)) * 1440)` | Resolved/Closed |
| `sla_breach_rate` (0–1) | `AVG(CASE WHEN <minutes> > s.target_minutes THEN 1.0 ELSE 0.0 END)` (joins `sla_targets s`) | Resolved/Closed |
| `reopen_rate` (0–1) | `AVG(CASE WHEN i.reopened_count > 0 THEN 1.0 ELSE 0.0 END)` | none |

A metric query is always composed the same way:
`SELECT <sql_expression> FROM <base_table> <alias> <required_joins> WHERE <filters> [AND …]`.
`compose_metric_sql()` does this for the build checks, `api/services.py` does it for the
dashboard, and the agent is told to do it. **No formula is written anywhere else.**

### Glossary: the business vocabulary

Each term has a **kind**: `entity` (incident, team…), `value` (critical priority = P1…),
`metric` (SLA breach…), `time` (last month, next week…) or `concept`. Examples:

| Term | Synonyms | SQL hint |
|---|---|---|
| SLA breach | breach, breached, missed SLA, late… | `i.status IN ('Resolved','Closed') AND <minutes> > s.target_minutes` |
| last month | previous month, prior month | `{time_column} >= date('2026-09-28','start of month','-1 month') AND {time_column} < date('2026-09-28','start of month')` |
| assignee | assigned to, owner, who fixed… | *(none: `is_answerable = 0`, so the question is refused)* |

`{time_column}` is filled in with the column the question is about (for example
`i.opened_at`); `{n}` is a number from the question ("severity 2").

**Not answerable from this data** (refused before any AI call): assignee, caller, response
time, downtime, impact, actual change window, change-caused incident.

**Flagged ambiguous** (the agent picks the documented default and states its assumption):
Resolved vs Closed, which team, SLA target meaning, change risk, "closed", "overdue",
"next week", "impact".

## Looking up a phrase: `find_term()` and `singular()`

`find_term(conn, phrase)` matches a phrase to a glossary term by name or synonym, ignoring
case. If nothing matches, it tries again with each word made singular by `singular()`
("tickets" → ticket → *incident*, "P1s" → *critical priority*), while leaving words like
"status" and "analysis" alone. The agent calls it for every 1–4-word phrase in a question.

## The self-checks (the build fails loudly)

| Function | Checks |
|---|---|
| `check_drafts` | Every hand-written column/table entry still matches `schema.sql` |
| `check_tables_and_joins` | Table descriptions and join paths match the schema's foreign keys |
| `check_glossary` | Every referenced column and metric exists; no phrase belongs to two unflagged terms (`find_synonym_clashes`) |
| `hint_test_queries` | Every `sql_hint` actually runs, with sample values for the placeholders |
| lookup checks | 16 plural/variant phrases resolve to the right term |

## Changing a definition safely

1. Change one entry in `build_catalog.py`.
2. Rebuild the catalog (`/build-catalog` in Claude Code).
3. Re-run the **whole** golden set (`/run-evals`), more than once, because the AI is not fully
   deterministic.
4. If a catalog change has no effect, look for a conflicting hard-coded rule in
   `agent/nl2sql.py` `build_context()`: prompt rules outrank catalog notes.
