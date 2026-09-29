# semantics/

The **semantic layer**: `meta_*` tables that live inside `db/tickets.sqlite` and give the NL2SQL
agent the context the Day 1 naive spike was missing.

Build it with `python semantics/build_catalog.py`, always after `python db/seed.py` (seeding
recreates the database file and wipes these tables).

| table | contents |
|---|---|
| `meta_columns` | every column: type, keys, allowed values, description, example, PII flag, ambiguity flag, synonyms |
| `meta_metrics` | `mttr`, `sla_breach_rate`, `reopen_rate` as reusable SQL fragments |
| `meta_glossary` | business terms users say ("P1", "team", "missed SLA", "last month") mapped to SQL hints; terms the data cannot answer are marked |
| `meta_tables` | table descriptions (not populated yet) |
| `meta_joins` | join paths (not populated yet) |

Priority wording (P1 / Sev1 / Critical …) is defined once in `PRIORITY_LEVELS` in
`build_catalog.py`; update it there only.
