"""Semantic catalog: the business meaning the agent is given (glossary, metrics, columns, joins)."""

import pandas as pd
import streamlit as st

from api_client import APIError, cached_get, hero, setup, sidebar

setup("Catalog")
sidebar()
dataset = st.session_state["dataset"]

hero("Semantic catalog", "The business meaning the model is given: glossary, metrics, columns and"
                         " joins. Ambiguous and not-answerable items are flagged.")


def load(section):
    try:
        return pd.DataFrame(cached_get(f"/api/catalog/{section}", dataset=dataset))
    except APIError as exc:
        st.error(str(exc))
        st.stop()


glossary_tab, metrics_tab, columns_tab, tables_tab, joins_tab = st.tabs(
    ["Glossary", "Metrics", "Columns", "Tables", "Joins"])

with glossary_tab:
    g = load("glossary")
    c1, c2, c3 = st.columns([3, 2, 2])
    text = c1.text_input("Search terms and synonyms", placeholder="e.g. sev1, breach, last month")
    kinds = c2.multiselect("Kind", sorted(g["kind"].unique()))
    only = c3.radio("Show", ["All", "Ambiguous", "Not answerable"], horizontal=True)
    view = g
    if text:
        needle = text.lower()
        view = view[view["term"].str.lower().str.contains(needle, regex=False)
                    | view["synonyms"].fillna("").str.lower().str.contains(needle, regex=False)]
    if kinds:
        view = view[view["kind"].isin(kinds)]
    if only == "Ambiguous":
        view = view[view["is_ambiguous"] == 1]
    elif only == "Not answerable":
        view = view[view["is_answerable"] == 0]
    view = view.assign(answerable=view["is_answerable"].map({1: "yes", 0: "no"}),
                       ambiguous=view["is_ambiguous"].map({1: "yes", 0: ""}))
    st.dataframe(view[["term", "kind", "synonyms", "definition", "sql_hint", "metric_name",
                       "answerable", "ambiguous", "ambiguity_note"]],
                 hide_index=True, width="stretch", height=520)
    st.caption(f"{len(view)} of {len(g)} terms")

with metrics_tab:
    for m in load("metrics").to_dict("records"):
        with st.container(border=True):
            st.markdown(f"**{m['metric_name']}** · {m['unit']}")
            st.write(m["description"])
            sql = (f"SELECT {m['sql_expression']}\nFROM {m['base_table']} {m['base_alias']}"
                   + (f"\n{m['required_joins']}" if m["required_joins"] else "")
                   + (f"\nWHERE {m['filters']}" if m["filters"] else ""))
            st.code(sql, language="sql")
            if m["notes"]:
                st.caption(m["notes"])

with columns_tab:
    cols = load("columns")
    table = st.selectbox("Table", sorted(cols["table_name"].unique()))
    view = cols[cols["table_name"] == table].assign(
        pii=lambda d: d["is_pii"].map({1: "PII", 0: ""}),
        ambiguous=lambda d: d["is_ambiguous"].map({1: "yes", 0: ""}))
    st.dataframe(view[["column_name", "data_type", "description", "allowed_values", "references_to",
                       "example_value", "synonyms", "pii", "ambiguous", "ambiguity_note"]],
                 hide_index=True, width="stretch")

with tables_tab:
    st.dataframe(load("tables"), hide_index=True, width="stretch")

with joins_tab:
    st.dataframe(load("joins"), hide_index=True, width="stretch")
