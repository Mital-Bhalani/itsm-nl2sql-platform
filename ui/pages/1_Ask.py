"""Ask: plain-English question -> answer, chart, SQL, rows, follow-ups. Optionally compare two models."""

from concurrent.futures import ThreadPoolExecutor

import altair as alt
import pandas as pd
import streamlit as st

from api_client import APIError, current_model, hero, post, setup, sidebar

setup("Ask")
health = sidebar()

EXAMPLES = [
    "Which assignment groups breached SLA most last month?",
    "What is the SLA breach rate by team last month?",
    "How many P1 incidents are open?",
    "What is the MTTR for each priority?",
    "How many incidents were opened each month?",
    "Which high-risk changes are scheduled next week?",
]

hero("Ask a question", "Plain English in, a checked answer out. The SQL behind every answer is "
                       "one click away.")

configured = [p for p in health["providers"] if p["configured"]]
compare = st.sidebar.toggle("Compare two models", value=False, disabled=len(health["providers"]) < 2,
                            help="Run the same question on a second provider side by side.")
second = None
if compare:
    others = [p for p in health["providers"] if p["name"] != st.session_state["provider"]]
    second_name = st.sidebar.selectbox("Second provider", [p["name"] for p in others],
                                       format_func=lambda n: next(p["label"] for p in others if p["name"] == n))
    second_spec = next(p for p in others if p["name"] == second_name)
    second_model = st.sidebar.text_input("Second model", value=second_spec["default_model"])
    second = (second_name, second_model)
    if not second_spec["configured"]:
        st.sidebar.warning(f"No API key for {second_spec['label']}; that side will show an error.")
if st.sidebar.button("Clear conversation"):
    st.session_state["history"] = []

st.session_state.setdefault("history", [])
st.session_state.setdefault("feedback_sent", set())


def call(question, provider, model, dataset):
    """Runs in a worker thread: must not touch st.* (no Streamlit context there)."""
    try:
        return post("/api/ask", {"question": question, "provider": provider, "model": model or None,
                                 "dataset": dataset})
    except APIError as exc:
        return {"question": question, "error": str(exc), "provider": provider, "model": model}


def auto_chart(frame):
    """A bar chart (or a line chart for months/dates) when the result is one label plus numbers."""
    if len(frame) < 2 or len(frame) > 60:
        return None
    numeric = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])
               and not c.lower().endswith("id") and c.lower() != "id"]
    labels = [c for c in frame.columns if c not in numeric and not c.lower().endswith("id")]
    if not numeric:
        return None
    if not labels:
        if "priority" in frame.columns:  # e.g. MTTR per priority: show priority as a label
            frame = frame.assign(priority=frame["priority"].map(lambda p: f"P{p}"))
            labels, numeric = ["priority"], [c for c in numeric if c != "priority"]
        if not labels or not numeric:
            return None
    label, measure = labels[0], numeric[0]
    looks_like_time = (label.lower() in ("month", "week", "day", "date")
                       or frame[label].astype(str).str.match(r"^\d{4}-\d{2}").all())
    base = alt.Chart(frame)
    if looks_like_time:
        return base.mark_line(point=True, color="#4F46E5", strokeWidth=2.5).encode(
            x=alt.X(f"{label}:O", title=None), y=alt.Y(f"{measure}:Q", title=measure.replace("_", " ")),
            tooltip=list(frame.columns))
    return base.mark_bar(cornerRadiusEnd=4, color="#4F46E5").encode(
        x=alt.X(f"{measure}:Q", title=measure.replace("_", " ")),
        y=alt.Y(f"{label}:N", sort="-x", title=None), tooltip=list(frame.columns))


def send_feedback(result, key, question):
    rating = st.feedback("thumbs", key=f"fb_{key}")
    if rating is None or key in st.session_state["feedback_sent"] or not result.get("request_id"):
        return
    try:
        post("/api/feedback", {"request_id": result["request_id"], "rating": "up" if rating else "down",
                               "question": question})
        st.session_state["feedback_sent"].add(key)
        st.toast("Thanks — feedback recorded.")
    except APIError as exc:
        st.toast(f"Feedback not saved: {exc}")


def render(result, key, question, latest):
    if result.get("refusal"):
        st.warning(result["refusal"], icon="🚫")
        return
    if result.get("error") and not result.get("sql"):
        st.error(result["error"])
        return
    if result.get("answer"):
        st.markdown(f"#### {result['answer']}")
    if result.get("error"):
        st.error(result["error"])
    if result.get("assumption"):
        st.info(f"Assumption: {result['assumption']}", icon="ℹ️")
    if result.get("columns"):
        frame = pd.DataFrame(result["rows"], columns=result["columns"])
        chart = auto_chart(frame)
        tabs = st.tabs((["📊 Chart"] if chart is not None else []) + ["📋 Table", "🧾 SQL"])
        offset = 0
        if chart is not None:
            with tabs[0]:
                st.altair_chart(chart, width="stretch")
            offset = 1
        with tabs[offset]:
            st.dataframe(frame, hide_index=True, width="stretch")
            note = " (capped at 1,000 rows)" if result.get("truncated") else ""
            st.caption(f"{result['row_count']} rows{note}")
            st.download_button("Download CSV", frame.to_csv(index=False).encode("utf-8"),
                               file_name="answer.csv", mime="text/csv", key=f"csv_{key}")
        with tabs[offset + 1]:
            if result.get("repaired"):
                st.caption("The first SQL failed; this is the corrected version.")
            st.code(result["sql"], language="sql")
    elif result.get("sql"):
        with st.expander("SQL"):
            st.code(result["sql"], language="sql")
    timings = result.get("timings") or {}
    tokens = ""
    if result.get("tokens_in") is not None:
        tokens = f" · {result['tokens_in']:,} in / {result.get('tokens_out') or 0:,} out tokens"
    foot = st.columns([4, 1])
    foot[0].caption(f"{result.get('provider')} / {result.get('model')} · "
                    f"{timings.get('total_ms', 0) / 1000:.1f} s{tokens}")
    with foot[1]:
        send_feedback(result, key, question)
    if latest and result.get("followups"):
        st.markdown("**Ask next:**")
        cols = st.columns(len(result["followups"]))
        for n, (col, followup) in enumerate(zip(cols, result["followups"])):
            if col.button(followup, key=f"next_{key}_{n}", width="stretch"):
                st.session_state["pending"] = followup
                st.rerun()


def show(entry, index, latest):
    with st.chat_message("user"):
        st.markdown(entry["question"])
    with st.chat_message("assistant"):
        if len(entry["results"]) == 1:
            render(entry["results"][0], f"{index}_0", entry["question"], latest)
        else:
            columns = st.columns(len(entry["results"]))
            for n, (column, result) in enumerate(zip(columns, entry["results"])):
                with column:
                    st.markdown(f"**{result.get('provider')} / {result.get('model')}**")
                    render(result, f"{index}_{n}", entry["question"], latest and n == 0)


question = st.chat_input("Ask about incidents, SLAs, teams or changes…")
question = question or st.session_state.pop("pending", None)
if question:
    targets = [current_model()] + ([second] if second else [])
    with st.spinner("Writing SQL, running it and reading the result…"):
        with ThreadPoolExecutor(max_workers=len(targets)) as pool:
            dataset = st.session_state["dataset"]
            results = list(pool.map(lambda t: call(question, *t, dataset), targets))
    st.session_state["history"].append({"question": question, "results": results})

history = st.session_state["history"]
for index, entry in enumerate(history):
    show(entry, index, latest=index == len(history) - 1)

if not history:
    st.markdown("**Try one of these:**")
    buttons = st.columns(3)
    for n, example in enumerate(EXAMPLES):
        if buttons[n % 3].button(example, width="stretch"):
            st.session_state["pending"] = example
            st.rerun()
    if not configured:
        st.warning("No model API key is configured, so questions cannot be answered yet.")
