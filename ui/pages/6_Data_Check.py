"""Data check: prove the UI shows what is in the database, and query the database yourself."""

import pandas as pd
import streamlit as st

from api_client import APIError, get, hero, post, setup, sidebar

setup("Data check")
health = sidebar()
dataset = st.session_state["dataset"]
info = health["datasets"][dataset]

hero("Data check", "Prove the UI shows what is in the database, and query the database yourself "
                   "(read-only).")

c = st.columns(4)
c[0].metric("Connected database", info["file"])
c[1].metric("Size", f"{info['size_mb']} MB")
c[2].metric("Last changed (UTC)", info["modified"].replace("T", " ")[:16])
c[3].metric("Semantic catalog", "present" if info["catalog"] else "missing")

st.subheader("UI numbers vs the database")
st.caption("Left column: the value the Home, Dashboard and Explorer pages show. Right column: the "
           "same number computed directly on the database, written separately from the "
           "dashboard's own formulas. Any difference is flagged.")
try:
    result = get("/api/reconcile", dataset=dataset)  # never cached: always the current database
except APIError as exc:
    st.error(str(exc))
    st.stop()

if result["passed"] == result["total"]:
    st.success(f"All {result['total']} checks match the database.")
else:
    st.error(f"{result['total'] - result['passed']} of {result['total']} checks do not match.")
checks = pd.DataFrame(result["checks"])
checks["result"] = checks["match"].map({True: "✅ match", False: "❌ differs"})
st.dataframe(checks[["check", "where_shown", "shown_in_ui", "in_database", "result"]].astype(
    {"shown_in_ui": str, "in_database": str}), hide_index=True, width="stretch")
with st.expander("SQL used for each check"):
    for row in result["checks"]:
        st.markdown(f"**{row['check']}**")
        st.code(row["sql"], language="sql")

st.subheader("Query the database yourself")
st.caption("Read-only. One SELECT; LIMIT 1000 added if missing; 5-second timeout; user names blocked.")
EXAMPLES = {
    "Incidents by priority": "SELECT priority, COUNT(*) AS incidents FROM incidents GROUP BY priority",
    "Open incidents by team": "SELECT g.name AS team, COUNT(*) AS open_incidents\nFROM incidents i\n"
                              "JOIN assignment_groups g ON g.id = i.assignment_group_id\n"
                              "WHERE i.status IN ('New', 'In Progress', 'On Hold')\nGROUP BY g.name ORDER BY 2 DESC",
    "Latest 20 incidents": "SELECT * FROM incidents ORDER BY opened_at DESC LIMIT 20",
    "Upcoming changes": "SELECT id, description, risk, status, planned_start FROM changes\n"
                        "WHERE planned_start >= '2026-09-28' ORDER BY planned_start",
    "SLA targets": "SELECT * FROM sla_targets",
}
example = st.selectbox("Start from an example", list(EXAMPLES))
sql = st.text_area("SQL", value=EXAMPLES[example], height=150, key=f"sql_{example}")
if st.button("Run query", type="primary"):
    try:
        out = post("/api/sql", {"sql": sql, "dataset": dataset})
    except APIError as exc:
        st.error(str(exc))
    else:
        frame = pd.DataFrame(out["rows"], columns=out["columns"])
        st.dataframe(frame, hide_index=True, width="stretch")
        note = " (capped at 1,000)" if out["truncated"] else ""
        st.caption(f"{out['row_count']} rows{note} · ran: {out['sql'].splitlines()[-1]}")
        st.download_button("Download CSV", frame.to_csv(index=False).encode("utf-8"),
                           file_name="query.csv", mime="text/csv")
