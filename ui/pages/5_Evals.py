"""Evals: score the agent against a golden set, per model, and compare runs."""

import html
import time

import pandas as pd
import streamlit as st

from api_client import APIError, current_model, get, hero, post, setup, sidebar

setup("Evals")
health = sidebar()

hero("Evaluation", "Score the agent against the golden set: the SQL must return the same rows as "
                   "the reference. Self-test is free; live runs use API credits.")

with st.form("run"):
    c1, c2, c3 = st.columns(3)
    golden = c1.selectbox("Golden set", ["golden_set.yaml", "golden_set_large.yaml"])
    mode = c2.radio("Mode", ["self-test", "live"], horizontal=True)
    provider, model = current_model()
    c3.markdown(f"**Model for live runs**  \n{html.escape(str(provider))} / {html.escape(str(model))}  \n"
                "<small>change it in the sidebar</small>", unsafe_allow_html=True)
    submitted = st.form_submit_button("Run evaluation", type="primary")

if submitted:
    body = {"golden": golden, "mode": mode}
    if mode == "live":
        body.update(provider=provider, model=model or None)
    try:
        job = post("/api/evals", body)
    except APIError as exc:
        st.error(str(exc))
        st.stop()
    bar = st.progress(0.0, text="Starting…")
    while job["status"] in ("queued", "running"):
        time.sleep(1.0)
        try:
            job = get(f"/api/evals/{job['id']}")
        except APIError as exc:
            st.error(str(exc))
            st.stop()
        done = job["completed"] / job["total"] if job["total"] else 1.0
        bar.progress(done, text=f"{job['completed']} / {job['total']} questions · {job['passed']} passed")
    bar.empty()
    st.session_state.setdefault("eval_runs", []).append(job)

runs = st.session_state.get("eval_runs", [])
if not runs:
    try:
        past = get("/api/evals")
    except APIError:
        past = []
    if past:
        st.info(f"The API holds {len(past)} earlier run(s); start a new run to see results here.")
    st.stop()

summary = pd.DataFrame([{
    "started": r["started_at"], "golden set": r["golden"], "mode": r["mode"],
    "model": f"{r['provider']} / {r['model']}" if r["provider"] else "(reference SQL)",
    "passed": f"{r['passed']} / {r['total']}",
    "accuracy %": round(100 * r["execution_accuracy"], 1) if r["execution_accuracy"] is not None else None,
    "status": r["status"]} for r in runs])
st.subheader("Runs this session")
st.dataframe(summary, hide_index=True, width="stretch")

latest = runs[-1]
if latest["status"] == "failed":
    st.error(latest["error"])
st.subheader("Latest run, per question")
STATUS_ICON = {"pass": "✅ pass", "wrong_result": "❌ wrong result", "sql_error": "⚠️ SQL error",
               "unsafe": "🛑 unsafe", "no_sql": "∅ no SQL"}
detail = pd.DataFrame([{"id": r["id"], "category": r["category"], "status": STATUS_ICON.get(r["status"], r["status"]),
                        "question": r["question"], "error": r["error"]} for r in latest["results"]])
if not detail.empty:
    st.dataframe(detail, hide_index=True, width="stretch")
    failed = [r for r in latest["results"] if r["status"] != "pass"]
    for r in failed:
        with st.expander(f"{r['id']} · {r['question']}"):
            if r.get("assumption"):
                st.info(f"Assumption: {r['assumption']}")
            if r.get("generated_sql"):
                st.code(r["generated_sql"], language="sql")
            left, right = st.columns(2)
            left.markdown("**Expected rows**")
            left.write(r["expected_rows"])
            right.markdown("**Actual rows**")
            right.write(r["actual_rows"])
