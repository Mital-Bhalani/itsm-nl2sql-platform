"""Incident: one incident in full — SLA gauge, timeline and similar incidents."""

import altair as alt
import pandas as pd
import streamlit as st

from api_client import (APIError, PRIORITY_COLORS, STATUS_COLORS, cached_get, hero, pill, setup,
                        sidebar)

setup("Incident")
sidebar()
dataset = st.session_state["dataset"]

hero("Incident detail", "How long it took against its SLA, what happened when, and what looks similar.")

default = st.session_state.get("incident_id") or st.query_params.get("id") or 1
c1, c2 = st.columns([1, 5])
incident_id = c1.number_input("Incident id", min_value=1, value=int(default), step=1)
st.session_state["incident_id"] = int(incident_id)
st.query_params["id"] = str(int(incident_id))

try:
    d = cached_get(f"/api/incidents/{int(incident_id)}", dataset=dataset)
except APIError as exc:
    st.warning(str(exc))
    st.stop()

with st.container(border=True):
    st.markdown(f"### #{d['id']} · {d['short_desc']}")
    st.html(pill(f"P{d['priority']}", PRIORITY_COLORS[d["priority"]])
            + pill(d["status"], STATUS_COLORS.get(d["status"], "#4B5563"))
            + pill(d["assignment_group"], "#4F46E5")
            + (pill(f"Reopened ×{d['reopened_count']}", "#DC2626") if d["reopened_count"] else ""))

    m = st.columns(5)
    m[0].metric("SLA target", f"{d['target_minutes'] / 60:g} h")
    if d["resolution_minutes"] is not None:
        m[1].metric("Time to resolve", f"{d['resolution_minutes'] / 60:.1f} h")
        verdict = "Breached" if d["sla_breached"] else "Met"
    elif "age_minutes" in d:
        m[1].metric("Open for", f"{d['age_minutes'] / 60:.1f} h")
        verdict = "Past target" if d["past_target"] else "Within target"
    else:
        m[1].metric("Time to resolve", "—")
        verdict = "Not measured (cancelled)"
    m[2].metric("SLA", verdict)
    m[3].metric("Opened", d["opened_at"][:16])
    m[4].metric("SLA due", d["sla_due_at"][:16])

left, right = st.columns([2, 3])
with left, st.container(border=True):
    st.subheader("SLA used")
    used = d["target_used_pct"]
    if used is None:
        st.info("A cancelled incident has no resolution time, so no SLA is measured.")
    else:
        color = "#DC2626" if used > 100 else "#EA580C" if used > 80 else "#16A34A"
        scale_max = max(150, used * 1.1)
        bands = pd.DataFrame([{"from": 0, "to": 80, "band": "ok"}, {"from": 80, "to": 100, "band": "close"},
                              {"from": 100, "to": scale_max, "band": "breach"}])
        back = alt.Chart(bands).mark_bar(height=34, opacity=0.18).encode(
            x=alt.X("from:Q", scale=alt.Scale(domain=[0, scale_max]), title="% of SLA target used"),
            x2="to:Q",
            color=alt.Color("band:N", scale=alt.Scale(domain=["ok", "close", "breach"],
                                                      range=["#16A34A", "#EA580C", "#DC2626"]), legend=None))
        value = alt.Chart(pd.DataFrame([{"used": used}])).mark_bar(height=16, color=color,
                                                                   cornerRadiusEnd=4).encode(
            x="used:Q", tooltip=[alt.Tooltip("used:Q", title="% used")])
        target = alt.Chart(pd.DataFrame([{"x": 100}])).mark_rule(color="#111827", strokeWidth=2,
                                                                 strokeDash=[4, 3]).encode(x="x:Q")
        st.altair_chart((back + value + target).properties(height=80), width="stretch")
        st.markdown(f"<div style='font-size:2rem;font-weight:700;color:{color}'>{used:g}%</div>"
                    f"of the {d['target_minutes'] / 60:g}-hour target used "
                    f"({'finished' if d['resolved_at'] else 'still running'}).", unsafe_allow_html=True)

with right, st.container(border=True):
    st.subheader("Timeline")
    events = pd.DataFrame(d["timeline"])
    events["at"] = pd.to_datetime(events["at"])
    palette = {"Opened": "#2563EB", "SLA due": "#111827", "Resolved": "#16A34A", "Closed": "#4B5563"}
    events["color"] = events["event"].map(palette).fillna("#DC2626")
    line = alt.Chart(events).mark_line(color="#CBD5E1", strokeWidth=3).encode(
        x=alt.X("at:T", title=None, axis=alt.Axis(format="%d %b %H:%M")), y=alt.value(40))
    points = alt.Chart(events).mark_circle(size=220, opacity=1).encode(
        x="at:T", y=alt.value(40), color=alt.Color("color:N", scale=None),
        tooltip=["event", alt.Tooltip("at:T", format="%Y-%m-%d %H:%M")])
    labels = alt.Chart(events).mark_text(dy=-22, fontSize=12, fontWeight="bold").encode(
        x="at:T", y=alt.value(40), text="event")
    st.altair_chart((line + points + labels).properties(height=110), width="stretch")
    for e in d["timeline"]:
        st.markdown(f"- **{e['event']}** — {e['at'][:16]} UTC")
    if d["reopened_count"]:
        st.caption(f"Reopened {d['reopened_count']} time(s); reopen dates are not stored, and the "
                   "resolution time is measured to the latest resolution.")

with st.container(border=True):
    st.subheader("Similar incidents")
    try:
        similar = cached_get(f"/api/incidents/{int(incident_id)}/similar", dataset=dataset)
    except APIError as exc:
        st.error(str(exc))
        similar = []
    if not similar:
        st.caption("No incidents share words with this description.")
    else:
        frame = pd.DataFrame(similar)[["id", "short_desc", "priority", "status", "assignment_group",
                                       "opened_at", "similarity"]]
        picked = st.dataframe(frame, hide_index=True, width="stretch", on_select="rerun",
                              selection_mode="single-row", key=f"similar_{int(incident_id)}",
                              column_config={"similarity": st.column_config.ProgressColumn(
                                  "Similarity", min_value=0, max_value=1.2, format="%.2f")})
        st.caption("Ranked by shared words in the description, same team and same priority. "
                   "Select a row to open it.")
        rows = picked.selection.rows if picked else []
        if rows:
            st.session_state["incident_id"] = int(frame.iloc[rows[0]]["id"])
            st.rerun()
