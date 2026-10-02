# agent/

**`nl2sql.py`** — the NL2SQL agent. It finds the business terms in a question using the semantic
catalog, builds the prompt entirely from the `meta_*` tables, asks the OpenAI API for one SQLite
query, and applies the guardrails (SELECT-only, single statement, read-only database, automatic
`LIMIT 1000`, no personal data). Questions about things the data does not record, such as an
incident's category or a person's email address, are refused before any API call. People are
reported by user id and role only (`users.name` is blocked).

```
python agent/nl2sql.py "which assignment groups breached SLA most last month?"
```

Needs `OPENAI_API_KEY` in the project-root `.env`, and the database and catalog built first
(`python db/seed.py`, `python semantics/build_catalog.py`).

**`naive_spike.py`** — the Day 1 naive spike. It sends one hard-coded question to the OpenAI API
with no schema context and no guardrails, and prints whatever comes back. It exists to show why
the naive approach fails (invented tables, wrong SQL dialect, the real clock instead of the data's
as-of date).

**Still to come:** turning the result rows into a plain-English answer shown alongside the SQL.
