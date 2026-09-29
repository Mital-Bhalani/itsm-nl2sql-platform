"""
NL2SQL agent: plain-English question -> semantic catalog context -> OpenAI -> guarded SQL.

    python agent/nl2sql.py "which assignment groups breached SLA most last month?"
    python agent/nl2sql.py --db db/tickets_large.sqlite "how many P1 incidents are open?"

Everything the model is told about the data comes from the meta_* catalog in
db/tickets.sqlite (built by semantics/build_catalog.py): table and column
descriptions, join paths, metric SQL and the business glossary. Nothing about the
schema is hard-coded here.

Guardrails:
    * questions that use a term the data cannot answer (e.g. "assignee") are refused
      before any API call
    * exactly one statement, SELECT or WITH only; write/admin keywords are rejected
    * the database is opened read-only
    * LIMIT 1000 is appended when the query has no LIMIT
    * users.name (personal data) is blocked at execution time by a SQLite authorizer
"""

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the repo free of __pycache__

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "tickets.sqlite"
ENV_PATH = ROOT / ".env"
sys.path.insert(0, str(ROOT / "semantics"))

from build_catalog import AS_OF, find_term  # noqa: E402

DEFAULT_MODEL = "gpt-4o-mini"
MAX_ROWS = 1000
MAX_PHRASE_WORDS = 4
PII_COLUMNS = {("users", "name")}
WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|"
    r"reindex|truncate|grant|revoke)\b", re.I)


class AgentAPIError(RuntimeError):
    """The language-model call failed (missing key, no credits, network). Not an SQL problem."""


class UnsafeSQL(ValueError):
    """The generated SQL broke a guardrail."""


# -----------------------------------------------------------------------------
#  Database access (read-only, personal data blocked)
# -----------------------------------------------------------------------------
def _authorizer(action, arg1, arg2, _db, _trigger):
    if action == sqlite3.SQLITE_READ and (arg1, arg2) in PII_COLUMNS:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def connect_readonly(db_path=None):
    """Open the database read-only; defaults to db/tickets.sqlite."""
    path = Path(db_path).resolve() if db_path else DB_PATH
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run: python db/seed.py && "
                                "python semantics/build_catalog.py")
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def run_sql(conn, sql):
    """Execute guarded SQL read-only. Returns (columns, rows). Reading users.name raises UnsafeSQL."""
    conn.set_authorizer(_authorizer)
    try:
        cur = conn.execute(sql)
        return [d[0] for d in cur.description], [list(r) for r in cur.fetchall()]
    except sqlite3.DatabaseError as exc:
        message = str(exc).lower()
        if "prohibited" in message or "not authorized" in message:  # raised by _authorizer
            raise UnsafeSQL("query reads personal data (users.name)") from exc
        raise
    finally:
        conn.set_authorizer(None)


# -----------------------------------------------------------------------------
#  Term resolution
# -----------------------------------------------------------------------------
def resolve_terms(conn, question):
    """Greedy longest-first match of question phrases to glossary terms (plural-aware)."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", question)
    found, i = [], 0
    while i < len(words):
        for size in range(min(MAX_PHRASE_WORDS, len(words) - i), 0, -1):
            phrase = " ".join(words[i:i + size])
            entry = find_term(conn, phrase)
            if entry:
                found.append((phrase, entry))
                i += size
                break
        else:
            i += 1
    return found


# -----------------------------------------------------------------------------
#  Prompt built from the catalog
# -----------------------------------------------------------------------------
def _rows(conn, sql):
    cur = conn.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def build_context(conn, resolved):
    lines = [
        "You translate questions about ITSM ticket data into ONE SQLite SELECT statement.",
        "",
        "RULES",
        f"- Today is {AS_OF} 00:00:00 UTC. Never use now(), CURRENT_DATE or the real clock; "
        f"compute relative dates from '{AS_OF}'.",
        "- SQLite dialect. Timestamps are TEXT 'YYYY-MM-DD HH:MM:SS' UTC.",
        "- Exactly one read-only SELECT (or WITH ... SELECT). No other statements.",
        "- Never select users.name (personal data).",
        "- Use the aliases i = incidents, c = changes, g = assignment_groups, u = users, "
        "s = sla_targets.",
        "- Use metric SQL and glossary hints below exactly as given; do not invent formulas.",
        "- When listing per team, start FROM assignment_groups g with LEFT JOIN so teams with "
        "zero rows appear with 0.",
        "- 'Most'/'top' questions: ORDER BY the measure DESC. Return the columns the question "
        "asks for.",
        "- If a term is marked AMBIGUOUS, pick the default in its hint and put one comment line "
        "first: -- assumption: <what you assumed>",
        "- Reply with only the SQL inside a ```sql code block.",
        "",
        "TABLES AND COLUMNS",
    ]
    for t in _rows(conn, "SELECT * FROM meta_tables ORDER BY table_name"):
        lines.append(f"{t['table_name']} ({t['grain']}): {t['description']}")
        for col in _rows(conn, "SELECT * FROM meta_columns WHERE table_name = "
                               f"'{t['table_name']}' ORDER BY rowid"):
            extra = f" Allowed: {col['allowed_values']}." if col["allowed_values"] else ""
            ref = f" FK -> {col['references_to']}." if col["references_to"] else ""
            pii = " PERSONAL DATA." if col["is_pii"] else ""
            amb = f" AMBIGUOUS: {col['ambiguity_note']}" if col["is_ambiguous"] else ""
            lines.append(f"  - {col['column_name']} {col['data_type']}: "
                         f"{col['description']}{extra}{ref}{pii}{amb}")
    lines += ["", "JOIN PATHS"]
    for j in _rows(conn, "SELECT * FROM meta_joins"):
        lines.append(f"- {j['left_table']}.{j['left_column']} = {j['right_table']}.{j['right_column']} "
                     f"({j['cardinality']}): {j['notes']}")
    lines += ["", "METRICS (compose as SELECT <sql_expression> FROM <base_table> <base_alias> "
                  "<required_joins> WHERE <filters> [AND other filters on <time_column>])"]
    for m in _rows(conn, "SELECT * FROM meta_metrics ORDER BY metric_name"):
        lines.append(f"- {m['metric_name']} ({m['unit']}): {m['description']} "
                     f"sql_expression: {m['sql_expression']} | base: {m['base_table']} {m['base_alias']} "
                     f"| required_joins: {m['required_joins'] or 'none'} | filters: {m['filters'] or 'none'} "
                     f"| time_column: {m['time_column']} | notes: {m['notes']}")
    lines += ["", "GLOSSARY ({time_column} = the column the question filters on; {n} = a number "
                  "from the question)"]
    for g in _rows(conn, "SELECT * FROM meta_glossary WHERE is_answerable = 1 ORDER BY kind, term"):
        hint = f" SQL: {g['sql_hint']}" if g["sql_hint"] else ""
        metric = f" Metric: {g['metric_name']}." if g["metric_name"] else ""
        amb = f" AMBIGUOUS: {g['ambiguity_note']}" if g["is_ambiguous"] else ""
        lines.append(f"- {g['term']} [{g['kind']}] (also: {g['synonyms'] or '-'}): "
                     f"{g['definition']}{hint}{metric}{amb}")
    if resolved:
        lines += ["", "TERMS FOUND IN THIS QUESTION"]
        for phrase, entry in resolved:
            lines.append(f"- \"{phrase}\" -> {entry['term']} [{entry['kind']}]")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
#  Model call and SQL guardrails
# -----------------------------------------------------------------------------
def _load_env():
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def call_model(system_prompt, question):
    _load_env()
    try:
        import openai
    except ModuleNotFoundError as exc:
        raise AgentAPIError("The 'openai' package is not installed: pip install -r requirements.txt") from exc
    try:
        client = openai.OpenAI()
        reply = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
            temperature=0,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": question}])
    except openai.OpenAIError as exc:
        raise AgentAPIError(f"{type(exc).__name__}: {exc}") from exc
    return reply.choices[0].message.content or ""


def extract_sql(text):
    """Return (sql, assumption) from the model reply."""
    block = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    sql = (block.group(1) if block else text).strip()
    assumption = None
    kept = []
    for line in sql.splitlines():
        match = re.match(r"\s*--\s*assumption:\s*(.*)", line, re.I)
        if match:
            assumption = match.group(1).strip()
        elif not line.strip().startswith("--"):
            kept.append(line)
    return "\n".join(kept).strip(), assumption


def guard_sql(sql):
    """Enforce SELECT-only, single statement, no write keywords, and a row LIMIT."""
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise UnsafeSQL("empty SQL")
    without_strings = re.sub(r"'(?:[^']|'')*'", "''", sql)
    if ";" in without_strings:
        raise UnsafeSQL("more than one statement")
    if not re.match(r"(select|with)\b", without_strings, re.I):
        raise UnsafeSQL("not a SELECT statement")
    if WRITE_WORDS.search(without_strings):
        raise UnsafeSQL(f"forbidden keyword: {WRITE_WORDS.search(without_strings).group(1).upper()}")
    if not re.search(r"\blimit\s+\d+(\s*(offset|,)\s*\d+)?\s*$", without_strings, re.I):
        sql = f"{sql}\nLIMIT {MAX_ROWS}"
    return sql


# -----------------------------------------------------------------------------
#  Public entry point
# -----------------------------------------------------------------------------
def translate(question, conn=None):
    """
    Translate a question into guarded SQL.
    Returns {question, terms, refusal, sql, assumption, unsafe}. Raises AgentAPIError when the
    model cannot be reached.
    """
    own = conn is None
    conn = conn or connect_readonly()
    try:
        resolved = resolve_terms(conn, question)
        result = {"question": question, "terms": [(p, e["term"]) for p, e in resolved],
                  "refusal": None, "sql": None, "assumption": None, "unsafe": None}
        blocked = [e for _, e in resolved if not e["is_answerable"]]
        if blocked:
            e = blocked[0]
            result["refusal"] = f"Cannot answer: '{e['term']}' is not in the data. {e['definition']}"
            return result
        reply = call_model(build_context(conn, resolved), question)
        sql, result["assumption"] = extract_sql(reply)
        try:
            result["sql"] = guard_sql(sql)
        except UnsafeSQL as exc:
            result["sql"], result["unsafe"] = sql, str(exc)
        return result
    finally:
        if own:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="Translate a question into SQL and run it.")
    parser.add_argument("question", nargs="+", help="the question in plain English")
    parser.add_argument("--db", type=Path, default=None,
                        help="database to query (default db/tickets.sqlite)")
    args = parser.parse_args()
    question = " ".join(args.question)
    conn = connect_readonly(args.db)
    try:
        result = translate(question, conn)
    except AgentAPIError as exc:
        sys.exit(f"Model call failed: {exc}")
    print(f"Question: {question}")
    print(f"Terms:    {', '.join(f'{p} -> {t}' for p, t in result['terms']) or '(none)'}")
    if result["refusal"]:
        print(result["refusal"])
        return
    if result["assumption"]:
        print(f"Assumed:  {result['assumption']}")
    print(f"SQL:\n{result['sql']}")
    if result["unsafe"]:
        sys.exit(f"Blocked: {result['unsafe']}")
    try:
        columns, rows = run_sql(conn, result["sql"])
    except (UnsafeSQL, sqlite3.Error) as exc:
        sys.exit(f"Query failed: {exc}")
    print("\n" + " | ".join(columns))
    for row in rows[:50]:
        print(" | ".join(str(v) for v in row))
    if len(rows) > 50:
        print(f"... {len(rows)} rows")


if __name__ == "__main__":
    main()
