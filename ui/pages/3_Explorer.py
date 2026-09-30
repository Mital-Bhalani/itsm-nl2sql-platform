"""Data explorer: browse every data table with filters, search, sort and paging."""

import pandas as pd
import streamlit as st

from api_client import APIError, cached_get, hero, setup, sidebar

setup("Explorer")
sidebar()
dataset = st.session_state["dataset"]

hero("Data explorer", "Browse every table in the database: filter, search, sort, page and export. "
                     "User names are masked.")

try:
    tables = cached_get("/api/tables", dataset=dataset)
except APIError as exc:
    st.error(str(exc))
    st.stop()

by_name = {t["table_name"]: t for t in tables}
order = [n for n in ("incidents", "changes", "assignment_groups", "users", "sla_targets") if n in by_name]
st.session_state.setdefault("explorer_table", "incidents")
table = st.segmented_control("Table", order, key="explorer_table",
                             format_func=lambda n: f"{n.replace('_', ' ')} ({by_name[n]['rows']:,})")
table = table or "incidents"
spec = by_name[table]
st.caption(f"{spec['description']} Grain: {spec['grain']}")

columns = spec["columns"]
with st.container(border=True):
    filters = {}
    filterable = [c for c in columns if c["allowed_values"] or c["column_name"] in ("priority", "assignment_group_id")]
    boxes = st.columns(max(len(filterable), 1) + 1)
    groups = {g["name"]: g["id"] for g in cached_get("/api/groups", dataset=dataset)}
    for box, col in zip(boxes, filterable):
        name = col["column_name"]
        if name == "assignment_group_id":
            choice = box.selectbox("Team", ["Any"] + list(groups), key=f"{table}_{name}")
            if choice != "Any":
                filters[name] = groups[choice]
        elif name == "priority":
            choice = box.selectbox("Priority", ["Any", 1, 2, 3, 4], key=f"{table}_{name}",
                                   format_func=lambda v: v if v == "Any" else f"P{v}")
            if choice != "Any":
                filters[name] = choice
        else:
            values = [v.strip().strip("'") for v in col["allowed_values"].split(",")]
            choice = box.selectbox(name.replace("_", " ").title(), ["Any"] + values, key=f"{table}_{name}")
            if choice != "Any":
                filters[name] = choice
    search = boxes[-1].text_input("Search text", key=f"{table}_search", placeholder="e.g. printer")

    s1, s2, s3 = st.columns([3, 1, 1])
    sortable = [c["column_name"] for c in columns if not c["is_pii"]]
    sort = s1.selectbox("Sort by", sortable, index=0, key=f"{table}_sort")
    desc = s2.toggle("Descending", value=table in ("incidents", "changes"), key=f"{table}_desc")
    size = s3.selectbox("Rows per page", [25, 50, 100, 200], index=1, key=f"{table}_size")

state_key = f"{table}_page"
signature = (tuple(sorted(filters.items())), search, sort, desc, size, dataset)
if st.session_state.get(f"{table}_sig") != signature:
    st.session_state[f"{table}_sig"] = signature
    st.session_state[state_key] = 1
page = st.session_state.get(state_key, 1)

params = {"dataset": dataset, "search": search or None, "sort": sort, "desc": desc,
          "page": page, "size": size, **{f"f_{k}": v for k, v in filters.items()}}
try:
    data = cached_get(f"/api/tables/{table}", **params)
except APIError as exc:
    st.error(str(exc))
    st.stop()

frame = pd.DataFrame(data["rows"], columns=data["columns"])
selection = st.dataframe(frame, hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", key=f"grid_{table}")

nav = st.columns([1, 2, 1])
if nav[0].button("◀ Previous", disabled=page <= 1):
    st.session_state[state_key] = page - 1
    st.rerun()
nav[1].markdown(f"<div style='text-align:center'>Page {data['page']} of {data['pages']} · "
                f"{data['total']:,} matching rows</div>", unsafe_allow_html=True)
if nav[2].button("Next ▶", disabled=page >= data["pages"]):
    st.session_state[state_key] = page + 1
    st.rerun()
st.download_button("Download this page as CSV", frame.to_csv(index=False).encode("utf-8"),
                   file_name=f"{table}_page{page}.csv", mime="text/csv")

if table == "incidents":
    picked = selection.selection.rows if selection else []
    if picked:
        incident_id = int(frame.iloc[picked[0]]["id"])
        try:
            detail = cached_get(f"/api/incidents/{incident_id}", dataset=dataset)
        except APIError as exc:
            st.error(str(exc))
            st.stop()
        with st.container(border=True):
            top = st.columns([5, 2])
            top[0].markdown(f"**Incident {detail['id']}** · {detail['short_desc']}")
            if top[1].button("Open incident page ▶", type="primary", width="stretch"):
                st.session_state["incident_id"] = detail["id"]
                st.switch_page("pages/7_Incident.py")
            d = st.columns(5)
            d[0].metric("Priority", f"P{detail['priority']}")
            d[1].metric("Status", detail["status"])
            d[2].metric("Team", detail["assignment_group"])
            d[3].metric("SLA target", f"{detail['target_minutes'] / 60:g} h")
            if detail["resolution_minutes"] is not None:
                d[4].metric("SLA", "Breached" if detail["sla_breached"] else "Met")
            elif "age_minutes" in detail:
                d[4].metric("SLA", "Past target" if detail["past_target"] else "Within target")
    else:
        st.caption("Select a row to see the incident's SLA summary and open its full page.")
