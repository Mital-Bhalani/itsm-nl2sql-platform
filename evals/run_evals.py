"""
Eval harness: score the NL2SQL agent on evals/golden_set.yaml by execution accuracy.

    python evals/run_evals.py              # live: agent translates each question via OpenAI
    python evals/run_evals.py --json       # same, machine-readable (used by /run-evals)
    python evals/run_evals.py --self-test  # no API: feeds each reference_sql through the same
                                           # guardrails, execution and scoring; must be 100%
    python evals/run_evals.py --golden evals/golden_set_large.yaml   # the large database

For each question the agent's SQL is run read-only on the golden file's `database`
(db/tickets.sqlite by default) and its rows are compared with the expected rows:
    * order-insensitive unless order_matters is true
    * numbers may differ by at most `tolerance` (default 0)
    * extra result columns are allowed if some of them match the expected columns
    * ambiguous questions also pass on any `alternatives` reading
    * refusal questions pass only when the agent refuses

Statuses: pass, wrong_result, sql_error, unsafe, no_sql. Execution accuracy = passed / total.
A model/API failure (missing key, no credits, network) stops the run instead of counting as
failed answers.
"""

import argparse
import json
import sqlite3
import sys
from itertools import permutations
from pathlib import Path

sys.dont_write_bytecode = True  # keep the repo free of __pycache__

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_SET = ROOT / "evals" / "golden_set.yaml"
sys.path.insert(0, str(ROOT / "agent"))

import nl2sql  # noqa: E402

MAX_PERMUTED_COLUMNS = 8


# -----------------------------------------------------------------------------
#  Result comparison
# -----------------------------------------------------------------------------
def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def cells_equal(actual, expected, tolerance):
    if _is_number(actual) and _is_number(expected):
        return abs(float(actual) - float(expected)) <= tolerance + 1e-9
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.strip() == expected.strip()
    return actual == expected


def rows_equal(actual, expected, tolerance):
    return len(actual) == len(expected) and all(
        cells_equal(a, e, tolerance) for a, e in zip(actual, expected))


def same_rows(actual_rows, expected_rows, order_matters, tolerance):
    if len(actual_rows) != len(expected_rows):
        return False
    if order_matters:
        return all(rows_equal(a, e, tolerance) for a, e in zip(actual_rows, expected_rows))
    unused = list(actual_rows)
    for expected in expected_rows:
        match = next((a for a in unused if rows_equal(a, expected, tolerance)), None)
        if match is None:
            return False
        unused.remove(match)
    return True


def results_match(actual_rows, expected_rows, order_matters, tolerance):
    """True if the actual rows, or some choice of their columns, equal the expected rows."""
    if not expected_rows:
        return not actual_rows
    width = len(expected_rows[0])
    actual_width = len(actual_rows[0]) if actual_rows else 0
    if actual_width < width:
        return False
    if actual_width > MAX_PERMUTED_COLUMNS:
        choices = [tuple(range(width))]
    else:
        choices = permutations(range(actual_width), width)
    for cols in choices:
        projected = [[row[i] for i in cols] for row in actual_rows]
        if same_rows(projected, expected_rows, order_matters, tolerance):
            return True
    return False


# -----------------------------------------------------------------------------
#  Scoring one question
# -----------------------------------------------------------------------------
def score(item, conn, self_test):
    expected = item["expected"]
    result = {"id": item["id"], "category": item["category"], "question": item["question"],
              "status": None, "generated_sql": None, "assumption": None, "terms": [],
              "expected_rows": expected.get("rows", []), "actual_rows": [], "error": None}

    if expected.get("refusal"):
        if self_test:  # term resolution and refusal need no API
            blocked = [e["term"] for _, e in nl2sql.resolve_terms(conn, item["question"])
                       if not e["is_answerable"]]
            refused = bool(blocked)
            result["error"] = None if refused else "no unanswerable term found"
        else:
            out = nl2sql.translate(item["question"], conn)
            result["terms"], result["generated_sql"] = out["terms"], out["sql"]
            refused = bool(out["refusal"])
            result["error"] = out["refusal"] if refused else "answered instead of refusing"
        result["status"] = "pass" if refused else "wrong_result"
        return result

    if self_test:
        raw_sql, unsafe = item["reference_sql"], None
    else:
        out = nl2sql.translate(item["question"], conn)
        result["terms"], result["assumption"] = out["terms"], out["assumption"]
        if out["refusal"]:
            result["status"], result["error"] = "no_sql", out["refusal"]
            return result
        raw_sql, unsafe = out["sql"], out["unsafe"]

    if unsafe:
        result.update(status="unsafe", generated_sql=raw_sql, error=unsafe)
        return result
    try:
        sql = nl2sql.guard_sql(raw_sql or "")
    except nl2sql.UnsafeSQL as exc:
        status = "no_sql" if str(exc) == "empty SQL" else "unsafe"
        result.update(status=status, generated_sql=raw_sql, error=str(exc))
        return result
    result["generated_sql"] = sql

    try:
        _, rows = nl2sql.run_sql(conn, sql)
    except nl2sql.UnsafeSQL as exc:
        result.update(status="unsafe", error=str(exc))
        return result
    except sqlite3.Error as exc:
        result.update(status="sql_error", error=str(exc))
        return result
    result["actual_rows"] = rows

    tolerance = float(item.get("tolerance", 0))
    order = bool(item.get("order_matters"))
    readings = [expected["rows"]] + [alt["rows"] for alt in item.get("alternatives") or []]
    matched = any(results_match(rows, r, order, tolerance) for r in readings)
    result["status"] = "pass" if matched else "wrong_result"
    return result


# -----------------------------------------------------------------------------
#  Run
# -----------------------------------------------------------------------------
def load_golden_file(path=GOLDEN_SET):
    """The whole golden-set file: questions plus header fields such as `database`."""
    try:
        import yaml
    except ModuleNotFoundError:
        sys.exit("PyYAML is not installed: pip install -r requirements.txt")
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_golden_set(path=GOLDEN_SET):
    return load_golden_file(path)["questions"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    parser.add_argument("--self-test", action="store_true",
                        help="score the reference SQL instead of calling the agent (no API)")
    parser.add_argument("--golden", type=Path, default=GOLDEN_SET,
                        help="golden-set file (default evals/golden_set.yaml)")
    parser.add_argument("--db", type=Path, default=None,
                        help="database to query (default: the golden file's `database` field)")
    args = parser.parse_args()

    golden = load_golden_file(args.golden)
    questions = golden["questions"]
    db_path = args.db or ROOT / golden.get("database", "db/tickets.sqlite")
    conn = nl2sql.connect_readonly(db_path)
    results = []
    for item in questions:
        try:
            results.append(score(item, conn, args.self_test))
        except nl2sql.AgentAPIError as exc:
            message = (f"Run stopped at {item['id']}: the model call failed, so no accuracy is "
                       f"reported. {exc}")
            if args.json:
                print(json.dumps({"error": message, "completed": len(results),
                                  "total": len(questions)}, ensure_ascii=False))
            else:
                print(message)
            sys.exit(2)
    conn.close()

    passed = sum(r["status"] == "pass" for r in results)
    total = len(results)
    report = {"mode": "self-test" if args.self_test else "live",
              "golden_set": Path(args.golden).name, "database": Path(db_path).name,
              "total": total, "passed": passed,
              "execution_accuracy": round(passed / total, 4) if total else 0.0, "results": results}

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"Eval run ({report['mode']}) on {report['golden_set']} against {report['database']}\n")
    for r in results:
        line = f"  {r['status'].upper():<13} {r['id']}  {r['question']}"
        if r["status"] != "pass" and r["error"]:
            line += f"\n                      {r['error']}"
        print(line)
    print(f"\nExecution accuracy: {passed}/{total} = {100 * passed / total:.1f}%")


if __name__ == "__main__":
    main()
