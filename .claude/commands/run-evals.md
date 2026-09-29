---
description: Run the eval harness and print execution accuracy and the 2 worst failures
---

Run the NL2SQL eval harness and report the execution accuracy and the 2 worst failures. Run everything from the project root with `python -B` so no `__pycache__` is written. Report only: do not edit any file, and never print secrets from `.env`.

1. **Guard:** if `evals/run_evals.py` does not exist, stop and report exactly:
   "Eval harness not built yet (evals/run_evals.py missing); see CLAUDE.md open item 3."
   The result is **NOT RUN**, which is neither PASS nor FAIL.
2. **Prepare:** if `db/tickets.sqlite` is missing, run `python -B db/seed.py`. Then always run `python -B semantics/build_catalog.py`, because the agent depends on the catalog. If either exits non-zero, report its error output and stop.
3. **Run:** `python -B evals/run_evals.py --json`. It must print one JSON object in this shape:
   ```json
   {"total": 20, "passed": 17, "execution_accuracy": 0.85,
    "results": [{"id": "q01", "question": "...",
                 "status": "pass | wrong_result | sql_error | unsafe | no_sql",
                 "generated_sql": "...", "expected_rows": [], "actual_rows": [], "error": null}]}
   ```
   If it exits non-zero without valid JSON, report the error output and stop. If the error is a missing OpenAI key or an exhausted OpenAI quota (for example `insufficient_quota`), say that this is the cause, not a harness bug.
4. **Report:**
   - **Execution accuracy** as a fraction and a percentage, for example `17/20 = 85.0%`. A question passes when its generated SQL runs read-only and returns the same result set as the reference SQL (order-insensitive unless the reference uses ORDER BY).
   - A count of results by status.
   - **The 2 worst failures**, ranked by severity: `unsafe` (non-SELECT or write attempt), then `sql_error`, then `no_sql`, then `wrong_result`. Break ties by the larger difference between expected and actual row counts. For each, show the id and question, the status, the generated SQL, the first few expected and actual rows, and the error message if any.
   - If there are fewer than 2 failures, say so.
