---
description: Rebuild the database, print row counts, and report whether the project is runnable
---

Rebuild the database, print the row counts of every table, and confirm the project is in a runnable state. Also report pass or fail plainly.

Steps (run from the project root, always with `python -B` so no `__pycache__` is written):

1. `python -B db/seed.py` — recreates `db/tickets.sqlite` from `db/schema.sql` and the synthetic data. This also wipes the meta_* catalog tables.
2. `python -B semantics/build_catalog.py` — rebuilds the meta_* catalog. Always run this after step 1.
3. Print the row count of every table, data and meta_*. Expected: assignment_groups 5, users 40, sla_targets 4, incidents 500, changes 100; meta_columns 23, meta_metrics 3, meta_glossary 42, meta_tables 0, meta_joins 0. Report any difference.
4. Check `PRAGMA foreign_key_check` is empty and `PRAGMA integrity_check` returns `ok`.
5. Check the environment: `openai`, `python-dotenv` and `httpx==0.27.2` importable, and `pip check` clean. Do not check for `.env` or `OPENAI_API_KEY`: the key is configured last, so its absence is expected and is not a failure.
6. Report PASS or FAIL for the database, the catalog and the environment separately, then an overall result.

Do not create or leave any files other than `db/tickets.sqlite`. Put any temporary files outside the repo.
