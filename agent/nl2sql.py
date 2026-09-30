"""
NL2SQL agent: plain-English question -> semantic catalog context -> OpenAI -> guarded SQL.

    python agent/nl2sql.py "which assignment groups breached SLA most last month?"
    python agent/nl2sql.py --db db/tickets_large.sqlite "how many P1 incidents are open?"
    python agent/nl2sql.py --provider anthropic "how many P1 incidents are open?"

Everything the model is told about the data comes from the meta_* catalog in
db/tickets.sqlite (built by semantics/build_catalog.py): table and column
descriptions, join paths, metric SQL and the business glossary. Nothing about the
schema is hard-coded here. The language model is reached through agent/llm.py (OpenAI or
Anthropic, chosen per call or by LLM_PROVIDER).

translate() turns a question into guarded SQL; ask() is the full pipeline used by the API:
translate -> run -> one repair attempt if SQLite rejects the SQL -> answer in plain English.

Guardrails:
    * questions that use a term the data cannot answer (e.g. "assignee") are refused
      before any API call
    * exactly one statement, SELECT or WITH only; write/admin keywords are rejected
    * the database is opened read-only
    * LIMIT 1000 is appended when the query has no LIMIT
    * a query running longer than 5 seconds is interrupted
    * users.name (personal data) is blocked at execution time by a SQLite authorizer
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True  # keep the repo free of __pycache__

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "tickets.sqlite"
sys.path.insert(0, str(ROOT / "semantics"))
sys.path.insert(0, str(ROOT / "agent"))

from build_catalog import AS_OF, find_term  # noqa: E402
from llm import AgentAPIError, complete  # noqa: E402,F401  (AgentAPIError re-exported)

MAX_ROWS = 1000
QUERY_TIMEOUT_MS = 5000
ANSWER_ROWS = 50
MAX_PHRASE_WORDS = 4
PII_COLUMNS = {("users", "name")}
WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|"
    r"reindex|truncate|grant|revoke)\b", re.I)


class UnsafeSQL(ValueError):
    """The generated SQL broke a guardrail."""


# -----------------------------------------------------------------------------
#  Database access (read-only, personal data blocked)
# -----------------------------------------------------------------------------
# Allow-list: a query may only select, read columns, call functions and recurse. Everything
# else (pragma table functions such as pragma_database_list, which reveal server file paths;
# ATTACH; writes) is denied even if it slips past the keyword check in guard_sql.
ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                   sqlite3.SQLITE_RECURSIVE}
BLOCKED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}
MAX_VALUE_BYTES = 1_000_000     # longest string/blob a query may build (stops zeroblob(1e9))
MAX_SQL_BYTES = 100_000
HEAP_LIMIT_BYTES = 512 * 1024 * 1024


def _denial(action, arg1, arg2):
    """Why an action is refused, or None when it is allowed."""
    if action not in ALLOWED_ACTIONS:
        return "query uses a statement or system function that is not allowed"
    if action == sqlite3.SQLITE_READ and (arg1, arg2) in PII_COLUMNS:
        return "query reads personal data (users.name)"
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in BLOCKED_FUNCTIONS:
        return f"function {arg2}() is not allowed"
    return None


def _authorizer(action, arg1, arg2, _db, _trigger):
    return sqlite3.SQLITE_DENY if _denial(action, arg1, arg2) else sqlite3.SQLITE_OK


def connect_readonly(db_path=None, check_same_thread=True):
    """
    Open the database read-only; defaults to db/tickets.sqlite. The API passes
    check_same_thread=False: each request owns its connection and uses it one step at a time,
    but FastAPI may open it and use it on different worker threads.

    Limits stop a single query from exhausting memory: values are capped at MAX_VALUE_BYTES,
    SQL text at MAX_SQL_BYTES, no other database may be attached, and SQLite's heap is capped.
    """
    path = Path(db_path).resolve() if db_path else DB_PATH
    if not path.exists():
        raise FileNotFoundError(f"{path.name} not found. Run: python db/seed.py && "
                                "python semantics/build_catalog.py")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True,
                           check_same_thread=check_same_thread)
    conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES)
    conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_BYTES)
    conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    conn.execute(f"PRAGMA hard_heap_limit = {HEAP_LIMIT_BYTES}")
    return conn


def run_sql(conn, sql, timeout_ms=QUERY_TIMEOUT_MS):
    """
    Execute guarded SQL read-only. Returns (columns, rows), at most MAX_ROWS rows whatever LIMIT
    the SQL has. Reading users.name or using a non-SELECT action raises UnsafeSQL; running
    longer than timeout_ms or needing too much memory raises sqlite3.OperationalError.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    denied = []

    def authorizer(action, arg1, arg2, _db, _trigger):
        reason = _denial(action, arg1, arg2)
        if reason:
            denied.append(reason)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorizer)
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = conn.execute(sql)
        return [d[0] for d in cur.description], [list(r) for r in cur.fetchmany(MAX_ROWS)]
    except MemoryError as exc:
        raise sqlite3.OperationalError("query needs too much memory") from exc
    except sqlite3.DatabaseError as exc:
        message = str(exc).lower()
        if denied or "prohibited" in message or "not authorized" in message:
            raise UnsafeSQL(denied[0] if denied else "query is not allowed") from exc
        if "interrupted" in message:
            raise sqlite3.OperationalError(f"query timed out after {timeout_ms / 1000:g} s") from exc
        if "too big" in message:
            raise sqlite3.OperationalError(
                f"query builds a value larger than {MAX_VALUE_BYTES:,} bytes") from exc
        raise
    finally:
        conn.set_authorizer(None)
        conn.set_progress_handler(None, 0)


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
        "- Only when the result has one row per team, start FROM assignment_groups g with LEFT "
        "JOIN so teams with zero rows appear with 0; then every filter on the joined tables "
        "(status, dates, priority) goes in the LEFT JOIN's ON clause, never in WHERE, and "
        "'zero X' questions use HAVING on the aggregated measure. Otherwise start FROM the "
        "table being counted and join nothing the question does not need.",
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
def call_model(system_prompt, question, provider=None, model=None):
    """One model call through agent/llm.py. Returns an LLMReply (text, provider, model, usage)."""
    return complete(system_prompt, question, provider=provider, model=model)


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
def _note_usage(result, reply):
    """Record which model answered and add its latency and token counts to the result."""
    result["provider"], result["model"] = reply.provider, reply.model
    result["llm_ms"] = result.get("llm_ms", 0) + reply.latency_ms
    for key in ("tokens_in", "tokens_out"):
        value = getattr(reply, key)
        if value is not None:
            result[key] = (result.get(key) or 0) + value


def _set_sql(result, reply_text):
    sql, assumption = extract_sql(reply_text)
    result["assumption"] = assumption or result.get("assumption")
    try:
        result["sql"], result["unsafe"] = guard_sql(sql), None
    except UnsafeSQL as exc:
        result["sql"], result["unsafe"] = sql, str(exc)


def translate(question, conn=None, provider=None, model=None, keep_context=False):
    """
    Translate a question into guarded SQL.
    Returns {question, terms, refusal, sql, assumption, unsafe, provider, model, llm_ms,
    tokens_in, tokens_out}. Raises AgentAPIError when the model cannot be reached.
    """
    own = conn is None
    conn = conn or connect_readonly()
    try:
        resolved = resolve_terms(conn, question)
        result = {"question": question, "terms": [(p, e["term"]) for p, e in resolved],
                  "refusal": None, "sql": None, "assumption": None, "unsafe": None,
                  "provider": None, "model": None, "llm_ms": 0,
                  "tokens_in": None, "tokens_out": None}
        blocked = [e for _, e in resolved if not e["is_answerable"]]
        if blocked:
            e = blocked[0]
            result["refusal"] = f"Cannot answer: '{e['term']}' is not in the data. {e['definition']}"
            return result
        context = build_context(conn, resolved)
        reply = call_model(context, question, provider, model)
        _note_usage(result, reply)
        _set_sql(result, reply.text)
        if keep_context:
            result["context"] = context
        return result
    finally:
        if own:
            conn.close()


ANSWER_PROMPT = (
    "You are a service-desk reporting analyst. Answer the manager's question in one to three "
    "plain-English sentences using ONLY the query result given. Quote the numbers exactly as "
    "they appear (add % only when the column is a percentage). If the result is empty, say that "
    "no matching records were found. If an assumption is listed, mention it briefly. Do not "
    "mention SQL, tables or columns.\n\n"
    "Also suggest three short follow-up questions a service manager might ask next that this "
    "data can answer (teams, priorities, statuses, SLA breaches, MTTR, reopen rate, changes by "
    "risk, time periods). Never suggest questions about named people, assignees or callers.\n\n"
    'Reply with JSON only: {"answer": "...", "followups": ["...", "...", "..."]}')


def _fallback_answer(columns, rows, truncated):
    if not rows:
        return "No matching records were found."
    if len(rows) == 1 and len(columns) == 1:
        return f"The answer is {rows[0][0]}."
    more = f" (capped at {len(rows)})" if truncated else ""
    return f"{len(rows)} rows returned{more}; see the table below."


def parse_answer(text):
    """(answer, followups) from the model's JSON reply; plain text is taken as the answer."""
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("answer"), str):
            followups = [f.strip() for f in data.get("followups") or [] if isinstance(f, str) and f.strip()]
            return data["answer"].strip(), followups[:3]
    return text.strip(), []


def summarise(question, result):
    """
    Plain-English answer and follow-up questions from the rows. Returns (answer, followups);
    falls back to a fixed sentence and no follow-ups if the model fails.
    """
    columns, rows = result["columns"], result["rows"]
    payload = {"question": question, "assumption": result["assumption"], "columns": columns,
               "rows": rows[:ANSWER_ROWS], "total_rows": len(rows)}
    fallback = _fallback_answer(columns, rows, result["truncated"])
    try:
        reply = call_model(ANSWER_PROMPT, json.dumps(payload, default=str),
                           result["provider"], result["model"])
    except AgentAPIError:
        return fallback, []
    _note_usage(result, reply)
    answer, followups = parse_answer(reply.text)
    return answer or fallback, followups


def _execute(conn, result):
    """Run result['sql']; on failure set result['error'] (and 'unsafe') and return False."""
    try:
        columns, rows = run_sql(conn, result["sql"])
    except UnsafeSQL as exc:
        result["unsafe"], result["error"] = str(exc), f"Blocked by guardrail: {exc}"
        return False
    result.update(columns=columns, rows=rows, row_count=len(rows),
                  truncated=len(rows) >= MAX_ROWS)
    return True


def ask(question, conn=None, provider=None, model=None, answer=True):
    """
    Full pipeline: translate, run read-only, repair once on an SQLite error, answer in words.
    Returns translate()'s keys plus {answer, followups, error, columns, rows, row_count, truncated,
    repaired, timings}. Raises AgentAPIError when the SQL model call itself fails.
    """
    own = conn is None
    conn = conn or connect_readonly()
    started = time.perf_counter()
    try:
        result = translate(question, conn, provider, model, keep_context=True)
        context = result.pop("context", None)
        result.update(answer=None, followups=[], error=None, columns=[], rows=[], row_count=0,
                      truncated=False, repaired=False, timings={})
        if result["refusal"]:
            result["answer"] = result["refusal"]
        elif result["unsafe"]:
            result["error"] = f"Blocked by guardrail: {result['unsafe']}"
        else:
            sql_started = time.perf_counter()
            try:
                ok = _execute(conn, result)
            except sqlite3.Error as exc:
                repair = (f"{question}\n\nYour previous SQL failed.\n```sql\n{result['sql']}\n```\n"
                          f"SQLite error: {exc}\nReturn the corrected SQL only.")
                try:
                    reply = call_model(context, repair, result["provider"], result["model"])
                except AgentAPIError as api_exc:
                    result["error"] = f"Query failed: {exc} (repair call failed: {api_exc})"
                    result["timings"]["total_ms"] = round((time.perf_counter() - started) * 1000)
                    return result
                _note_usage(result, reply)
                _set_sql(result, reply.text)
                result["repaired"] = True
                ok = False
                if result["unsafe"]:
                    result["error"] = f"Blocked by guardrail: {result['unsafe']}"
                else:
                    try:
                        ok = _execute(conn, result)
                    except sqlite3.Error as exc2:
                        result["error"] = f"Query failed after one repair attempt: {exc2}"
            result["timings"]["sql_ms"] = round((time.perf_counter() - sql_started) * 1000)
            if ok and answer:
                result["answer"], result["followups"] = summarise(question, result)
            elif ok:
                result["answer"] = _fallback_answer(result["columns"], result["rows"], result["truncated"])
        result["timings"]["llm_ms"] = result["llm_ms"]
        result["timings"]["total_ms"] = round((time.perf_counter() - started) * 1000)
        return result
    finally:
        if own:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="Translate a question into SQL and run it.")
    parser.add_argument("question", nargs="+", help="the question in plain English")
    parser.add_argument("--db", type=Path, default=None,
                        help="database to query (default db/tickets.sqlite)")
    parser.add_argument("--provider", default=None, help="openai or anthropic (default LLM_PROVIDER)")
    parser.add_argument("--model", default=None, help="model name (default: the provider's)")
    args = parser.parse_args()
    question = " ".join(args.question)
    conn = connect_readonly(args.db)
    try:
        result = ask(question, conn, args.provider, args.model)
    except AgentAPIError as exc:
        sys.exit(f"Model call failed: {exc}")
    finally:
        conn.close()
    print(f"Question: {question}")
    print(f"Terms:    {', '.join(f'{p} -> {t}' for p, t in result['terms']) or '(none)'}")
    if result["refusal"]:
        print(result["refusal"])
        return
    print(f"Model:    {result['provider']} / {result['model']}")
    if result["assumption"]:
        print(f"Assumed:  {result['assumption']}")
    print(f"SQL{' (repaired)' if result['repaired'] else ''}:\n{result['sql']}")
    if result["error"]:
        sys.exit(result["error"])
    print(f"\nAnswer:   {result['answer']}")
    for followup in result["followups"]:
        print(f"  next?   {followup}")
    columns, rows = result["columns"], result["rows"]
    print("\n" + " | ".join(columns))
    for row in rows[:50]:
        print(" | ".join(str(v) for v in row))
    if len(rows) > 50:
        print(f"... {len(rows)} rows")


if __name__ == "__main__":
    main()
