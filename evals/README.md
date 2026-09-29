# evals/

Measures the NL2SQL agent's **execution accuracy**: does the SQL it writes return the right rows?

- **`golden_set.yaml`** — 15 questions (easy lookups, ambiguous date ranges, multi-table joins
  and edge cases such as a team with zero results and a question that must be refused), each
  with reference SQL and the expected rows for `db/tickets.sqlite` (500 incidents).
- **`golden_set_large.yaml`** — the same 15 questions with expected rows for the large
  database `db/tickets_large.sqlite` (50,000 incidents).
- **`make_golden_set.py`** — generates both files by running each reference SQL on the
  database. Regenerate whenever `db/seed.py` or the database size changes.
- **`run_evals.py`** — the harness. It asks the agent each question, runs the SQL read-only
  on the database named in the golden file, and compares the rows with the expected ones.

```
python evals/run_evals.py                                     # live run (calls the OpenAI API)
python evals/run_evals.py --json                              # machine-readable, used by /run-evals
python evals/run_evals.py --self-test                         # no API: checks the harness itself
python evals/run_evals.py --golden evals/golden_set_large.yaml   # against the large database

python evals/make_golden_set.py                               # regenerate golden_set.yaml
python evals/make_golden_set.py --db db/tickets_large.sqlite --out evals/golden_set_large.yaml
```

Rows compare order-insensitively unless a question sets `order_matters`; numbers may differ by
the question's `tolerance`; extra columns are fine if some of them match; ambiguous questions
also pass on any listed alternative reading.
