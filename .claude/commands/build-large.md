---
description: Build the large test set in one go - seed db/tickets_large.sqlite, add the catalog, regenerate golden_set_large.yaml and self-test it
argument-hint: "[incidents changes] [live]"
---

Build the large-scale test set end to end and report the result. Arguments: $ARGUMENTS

Run everything from the project root with `python -B` (no `__pycache__`), stop at the first step that exits non-zero and report its error output, and never print secrets from `.env`.

**Sizes.** Default 50000 incidents and 10000 changes. If the arguments start with two numbers, use them as incidents and changes instead (minimum 100 and 20). If the arguments contain the word `live`, also run step 5.

1. **Seed:** `python -B db/seed.py --incidents <N> --changes <M> --out db/tickets_large.sqlite`. Report the row counts and the SLA breach line it prints; the breach rate must be exactly 15.0%.
2. **Catalog:** `python -B semantics/build_catalog.py --db db/tickets_large.sqlite`. Its own checks must pass (exit 0).
3. **Golden set:** `python -B evals/make_golden_set.py --db db/tickets_large.sqlite --out evals/golden_set_large.yaml`. Then run `git diff --stat evals/golden_set_large.yaml`:
   - at the default size the file must be **unchanged** (the data is deterministic); if it changed, report it as a problem
   - at a custom size it will change: say so, and warn that `golden_set_large.yaml` is committed, so the change should only be committed if the new size is meant to become the standard
4. **Self-test (no API):** `python -B evals/run_evals.py --golden evals/golden_set_large.yaml --self-test`. It must be 15/15.
5. **Live (only with `live`):** `python -B evals/run_evals.py --golden evals/golden_set_large.yaml`. This calls the OpenAI API 14 times. If it stops on a missing key or no credits, report that as the cause, not as a failure of the build.

**Report** one table with a row per step (command, result, time taken) and then:
- incidents, changes and users in `db/tickets_large.sqlite`, its file size, and the breach rate
- whether `golden_set_large.yaml` changed
- self-test result, and live accuracy if run
- an overall **PASS** or **FAIL**

Do not commit or push anything. `db/tickets_large.sqlite` is gitignored and stays local.
