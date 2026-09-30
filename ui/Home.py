"""
ITSM Insights — Streamlit front end for the NL2SQL platform.

    streamlit run ui/Home.py        # needs the API running (python run_app.py starts both)
"""

import streamlit as st

from api_client import APIError, cached_get, hero, setup, sidebar

setup("Home")
health = sidebar()

hero("ITSM Insights", "Ask questions about incidents, SLAs and changes in plain English. Every "
                      "answer shows the SQL it ran, read-only.")

status = health["status"]
cols = st.columns(3)
cols[0].metric("Service status", status.upper())
cols[1].metric("Model providers ready",
               f"{sum(p['configured'] for p in health['providers'])} / {len(health['providers'])}")
cols[2].metric("Data as of", health.get("as_of", "-"))
if status != "ok":
    st.warning("The default dataset or its catalog is missing. Run `python db/seed.py` and "
               "`python semantics/build_catalog.py`, then refresh.")
if not health["llm_ready"]:
    st.warning("No language-model API key is configured, so **Ask** and live evals will not work. "
               "Dashboards, the explorer and the catalog still do.")

try:
    info = cached_get("/api/overview", dataset=st.session_state["dataset"])
except APIError as exc:
    st.error(str(exc))
    st.stop()

st.subheader(f"Dataset: {st.session_state['dataset']}")
counts = info["row_counts"]
tiles = st.columns(len(counts))
for tile, (table, n) in zip(tiles, counts.items()):
    tile.metric(table.replace("_", " ").title(), f"{n:,}")
st.caption(f"Incidents opened {info['incidents_from'][:10]} to {info['incidents_to'][:10]} · "
           f"semantic catalog: {info['catalog_counts']['glossary']} glossary terms, "
           f"{info['catalog_counts']['metrics']} metrics, {info['catalog_counts']['columns']} columns.")

st.subheader("Where to go")
PAGES = [
    ("pages/1_Ask.py", "Ask a question", "💬", "Plain English in; answer, chart and SQL out. Compare two models."),
    ("pages/2_Dashboard.py", "Dashboard", "📈", "SLA, MTTR and reopen trends by team, month and priority."),
    ("pages/3_Explorer.py", "Data explorer", "🗂️", "Browse, filter and export every table in the database."),
    ("pages/7_Incident.py", "Incident detail", "🎫", "SLA gauge, timeline and similar incidents for one ticket."),
    ("pages/4_Catalog.py", "Semantic catalog", "📖", "The glossary, metrics and joins the model is given."),
    ("pages/5_Evals.py", "Evals", "✅", "Score the agent on the golden set, per model."),
    ("pages/6_Data_Check.py", "Data check", "🔎", "UI numbers vs the database, plus a read-only SQL console."),
]
for row in range(0, len(PAGES), 4):
    cards = st.columns(4)
    for card, (page, label, icon, text) in zip(cards, PAGES[row:row + 4]):
        with card, st.container(border=True):
            st.page_link(page, label=f"**{label}**", icon=icon)
            st.caption(text)

with st.expander("Safety and data handling"):
    st.markdown(
        "- The database is opened **read-only**; only a single `SELECT` statement can run, with "
        "a row limit and a 5-second timeout.\n"
        "- **Personal data** (`users.name`) is masked in the explorer and blocked in generated SQL.\n"
        "- Questions about data that does not exist (assignee, caller, downtime…) are **refused** "
        "instead of guessed.\n"
        "- Every question is recorded in the API's audit log with the SQL and model used.")
