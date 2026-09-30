"""Dashboard: headline KPIs with trends and period comparison, breakdowns, drill-down to incidents."""

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from api_client import APIError, PRIORITY_COLORS, STATUS_COLORS, cached_get, hero, setup, sidebar

setup("Dashboard")
sidebar()
dataset = st.session_state["dataset"]

hero("Service dashboard", "SLA performance, workload and change risk across every team.")

try:
    groups = cached_get("/api/groups", dataset=dataset)
except APIError as exc:
    st.error(str(exc))
    st.stop()

with st.container(border=True):
    f1, f2, f3 = st.columns([2, 2, 3])
    use_dates = f1.toggle("Filter by date opened", value=False,
                          help="Off: all data, with the last full month compared to the month before.")
    period = f2.date_input("Opened between", value=(date(2026, 8, 1), date(2026, 8, 31)),
                           disabled=not use_dates, format="YYYY-MM-DD")
    team_names = {g["name"]: g["id"] for g in groups}
    team = f3.selectbox("Team", ["All teams"] + list(team_names))

params = {"dataset": dataset}
if team != "All teams":
    params["group_id"] = team_names[team]
previous = None
if use_dates and isinstance(period, tuple) and len(period) == 2:
    start, end = period
    params.update(date_from=start.isoformat(), date_to=end.isoformat())
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    previous = {**params, "date_from": prev_start.isoformat(), "date_to": prev_end.isoformat()}

try:
    data = cached_get("/api/kpis", **params)
    before = cached_get("/api/kpis", **previous) if previous else None
except APIError as exc:
    st.error(str(exc))
    st.stop()

months = pd.DataFrame(data["by_month"])
h = data["headline"]

# Comparison: the chosen period vs the one before it, or (no dates) last full month vs the one before.
compare_label, prev_h = None, None
if before:
    compare_label = f"vs previous {days} days"
    prev_h = before["headline"]
    cur_h = h
elif len(months) >= 3:
    full = months[months["month"] < data["as_of"][:7]]  # drop the running month
    if len(full) >= 2:
        last, prior = full.iloc[-1], full.iloc[-2]
        compare_label = f"{last['month']} vs {prior['month']}"
        cur_h = {"incidents": last["incidents"], "sla_breaches": last["sla_breaches"],
                 "sla_breach_rate_pct": last["sla_breach_rate_pct"],
                 "mttr_hours": last["mttr_hours"], "reopen_rate_pct": last["reopen_rate_pct"]}
        prev_h = {"incidents": prior["incidents"], "sla_breaches": prior["sla_breaches"],
                  "sla_breach_rate_pct": prior["sla_breach_rate_pct"],
                  "mttr_hours": prior["mttr_hours"], "reopen_rate_pct": prior["reopen_rate_pct"]}


def delta(key, unit=""):
    if not prev_h or cur_h.get(key) is None or prev_h.get(key) is None:
        return None
    diff = round(float(cur_h[key]) - float(prev_h[key]), 1)
    return f"{diff:+g}{unit}"


def spark(column):
    return months[column].fillna(0).tolist() if column in months and len(months) > 1 else None


tiles = st.columns(6)
tiles[0].metric("Incidents", f"{h['incidents']:,}", delta("incidents"), delta_color="off",
                chart_data=spark("incidents"), chart_type="area", delta_description=compare_label)
tiles[1].metric("Open now", f"{h['open']:,}", help="Status New, In Progress or On Hold")
tiles[2].metric("SLA breaches", f"{h['sla_breaches']:,}", delta("sla_breaches"), delta_color="inverse",
                chart_data=spark("sla_breaches"), chart_type="bar", delta_description=compare_label,
                help="Resolved/Closed incidents whose resolution time exceeded the priority target")
tiles[3].metric("SLA breach rate", f"{h['sla_breach_rate_pct'] or 0}%", delta("sla_breach_rate_pct", " pts"),
                delta_color="inverse", chart_data=spark("sla_breach_rate_pct"), chart_type="line",
                delta_description=compare_label)
tiles[4].metric("MTTR", f"{h['mttr_hours'] or 0} h", delta("mttr_hours", " h"), delta_color="inverse",
                chart_data=spark("mttr_hours"), chart_type="line", delta_description=compare_label,
                help="Mean time to resolve, wall-clock hours")
tiles[5].metric("Reopen rate", f"{h['reopen_rate_pct'] or 0}%", delta("reopen_rate_pct", " pts"),
                delta_color="inverse", chart_data=spark("reopen_rate_pct"), chart_type="line",
                delta_description=compare_label)
note = f" Arrows compare {compare_label}; green = better." if compare_label else ""
st.caption(f"As of {data['as_of']}. Small charts show the monthly trend.{note}")


def open_team_in_explorer(team_name):
    st.session_state["explorer_table"] = "incidents"
    st.session_state["incidents_assignment_group_id"] = team_name
    st.switch_page("pages/3_Explorer.py")


teams = pd.DataFrame(data["by_team"])
if not teams.empty:
    left, right = st.columns([3, 2])
    with left, st.container(border=True):
        st.subheader("SLA breaches by team")
        measure = st.radio("Measure", ["Count", "Rate %"], horizontal=True, label_visibility="collapsed")
        field = "sla_breaches" if measure == "Count" else "sla_breach_rate_pct"
        pick = alt.selection_point(name="team_pick", fields=["team"])
        chart = alt.Chart(teams).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X(f"{field}:Q", title="Breaches" if measure == "Count" else "Breach rate %"),
            y=alt.Y("team:N", sort="-x", title=None),
            color=alt.condition(pick, alt.value("#4F46E5"), alt.value("#C7D2FE")),
            tooltip=["team", "sla_breaches", "sla_breach_rate_pct", "resolved"]).add_params(pick)
        event = st.altair_chart(chart, width="stretch", on_select="rerun", key="team_chart")
        chosen = (event.selection.get("team_pick") or [{}])[0].get("team") if event else None
        if chosen and chosen != st.session_state.get("_team_pick_done"):
            st.session_state["_team_pick_done"] = chosen  # a kept selection must not re-trigger
            open_team_in_explorer(chosen)
        elif not chosen:
            st.session_state.pop("_team_pick_done", None)
        st.caption("Click a bar to open that team's incidents in the explorer. Count and rate can "
                   "rank teams differently.")
    with right, st.container(border=True):
        st.subheader("Team scorecard")
        st.dataframe(teams[["team", "incidents", "open", "sla_breaches", "sla_breach_rate_pct",
                            "mttr_hours", "reopen_rate_pct"]],
                     column_config={
                         "team": "Team", "incidents": "Incidents", "open": "Open",
                         "sla_breaches": "Breaches",
                         "sla_breach_rate_pct": st.column_config.ProgressColumn(
                             "Breach %", format="%.1f%%", min_value=0, max_value=max(40, teams["sla_breach_rate_pct"].max())),
                         "mttr_hours": st.column_config.NumberColumn("MTTR h", format="%.1f"),
                         "reopen_rate_pct": st.column_config.NumberColumn("Reopen %", format="%.1f")},
                     hide_index=True, width="stretch")
        c1, c2 = st.columns([3, 2])
        drill = c1.selectbox("Team", teams["team"].tolist(), label_visibility="collapsed")
        if c2.button("Open incidents", width="stretch"):
            open_team_in_explorer(drill)

if not months.empty:
    with st.container(border=True):
        st.subheader("Monthly trend (by month opened)")
        base = alt.Chart(months).encode(x=alt.X("month:O", title=None))
        bars = base.mark_bar(opacity=0.35, color="#4F46E5", cornerRadiusEnd=3).encode(
            y=alt.Y("incidents:Q", title="Incidents"), tooltip=["month", "incidents", "sla_breaches"])
        line = base.mark_line(point=True, color="#DC2626", strokeWidth=2.5).encode(
            y=alt.Y("sla_breach_rate_pct:Q", title="Breach rate %"),
            tooltip=["month", "sla_breach_rate_pct", "mttr_hours"])
        st.altair_chart(alt.layer(bars, line).resolve_scale(y="independent"), width="stretch")

c1, c2, c3 = st.columns(3)
with c1, st.container(border=True):
    st.subheader("By priority")
    prio = pd.DataFrame(data["by_priority"])
    if not prio.empty:
        colors = [PRIORITY_COLORS[int(p[1:])] for p in prio["priority"]]
        st.altair_chart(alt.Chart(prio).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("priority:N", title=None), y=alt.Y("incidents:Q"),
            color=alt.Color("priority:N", scale=alt.Scale(domain=prio["priority"].tolist(), range=colors),
                            legend=None),
            tooltip=["priority", "incidents", "sla_breaches", "sla_breach_rate_pct"]), width="stretch")
with c2, st.container(border=True):
    st.subheader("By status")
    status = pd.DataFrame(data["by_status"])
    if not status.empty:
        st.altair_chart(alt.Chart(status).mark_arc(innerRadius=55).encode(
            theta="incidents:Q",
            color=alt.Color("status:N", scale=alt.Scale(domain=list(STATUS_COLORS),
                                                        range=list(STATUS_COLORS.values())),
                            legend=alt.Legend(orient="bottom", columns=3, title=None)),
            tooltip=["status", "incidents"]), width="stretch")
with c3, st.container(border=True):
    st.subheader("Upcoming changes by risk")
    changes = pd.DataFrame(data["upcoming_changes_by_risk"])
    if changes.empty:
        st.info("No open changes planned after the as-of date.")
    else:
        st.altair_chart(alt.Chart(changes).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("risk:N", sort=["High", "Moderate", "Low"], title=None), y="changes:Q",
            color=alt.Color("risk:N", scale=alt.Scale(domain=["High", "Moderate", "Low"],
                                                       range=["#DC2626", "#EA580C", "#16A34A"]),
                            legend=None),
            tooltip=["risk", "changes"]), width="stretch")
