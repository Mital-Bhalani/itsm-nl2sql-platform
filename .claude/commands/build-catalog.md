---
description: Rebuild the meta_* semantic catalog and report which tables and columns are still undocumented
---

Rebuild the semantic catalog and report what is still undocumented. Run everything from the project root with `python -B` so no `__pycache__` is written, and do not create or leave any files in the repo.

1. If `db/tickets.sqlite` does not exist, run `python -B db/seed.py` first.
2. Run `python -B semantics/build_catalog.py`. If it exits non-zero, stop and report its error output: the build's own checks failed (bad reference, SQL hint that does not run, synonym clash or term lookup problem).
3. Query `db/tickets.sqlite` read-only and report:
   - **Undocumented tables:** every data table (from `sqlite_master`, excluding `meta_%` and `sqlite_%`) with no row in `meta_tables`.
   - **Undocumented columns:** every data column with no row in `meta_columns`, or whose `description` is `(undocumented)` or empty.
   - **Ambiguous columns:** rows in `meta_columns` with `is_ambiguous = 1`, with their `ambiguity_note`.
   - **Columns without synonyms:** rows in `meta_columns` where `synonyms` is NULL (informational only; ID columns usually need none).
   - **Missing join paths:** foreign keys (from `PRAGMA foreign_key_list` on each data table) with no matching row in `meta_joins`.
   - Row counts of all five `meta_*` tables.
4. Present one summary table per category, then a one-line verdict: **FULLY DOCUMENTED** only if there are no undocumented tables, no undocumented columns and no missing join paths; otherwise **GAPS REMAIN** with the counts. Ambiguous columns and missing synonyms do not change the verdict, but list them.
5. Do not edit `semantics/build_catalog.py` or any other file. Only report.
