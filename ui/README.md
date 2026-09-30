# ui/ — Streamlit front end ("ITSM Insights")

A multipage Streamlit app. It never opens the database or calls a model itself: every page
goes through the API (`api_client.py`, `API_URL`, optional `APP_API_KEY`).

```bash
python run_app.py            # starts the API and this UI; open http://localhost:8501
```

| page | what you can do |
|---|---|
| `Home.py` | service status, providers ready, dataset size, page cards |
| `pages/1_Ask.py` | ask in plain English; answer, **automatic chart** (bar, or line for months), table (CSV), SQL, assumptions and refusals; **suggested follow-up questions**; **thumbs up/down** (saved to the audit log); **compare two models** side by side |
| `pages/2_Dashboard.py` | KPI tiles with **monthly sparklines** and **period comparison** (last full month vs the month before, or the chosen dates vs the same length before); team scorecard; charts by team, month, priority, status, upcoming change risk; **click a team bar (or "Open incidents") to open that team's incidents in the explorer** |
| `pages/3_Explorer.py` | browse every table with filters, text search, sort and paging; select an incident for its SLA summary and **open its full page** |
| `pages/7_Incident.py` | one incident: priority/status/team badges, **SLA gauge** (% of target used), **timeline** (opened, SLA due, resolved or now), **similar incidents** (shared description words, same team/priority) |
| `pages/4_Catalog.py` | glossary, metrics, columns, tables and joins the model is given; ambiguous and not-answerable items flagged |
| `pages/6_Data_Check.py` | which database file is connected (size, last changed), UI numbers vs direct SQL on the database (25 checks), and a read-only SQL console |
| `pages/5_Evals.py` | run the golden set (self-test or live, any provider/model) and compare runs |

Look and feel: `.streamlit/config.toml` (project root) sets the theme; `ui/assets/` holds the logo; `api_client.setup()` adds the logo and card styling, `hero()` the page header band.

The sidebar on every page picks the dataset (`default` / `large`), the model provider and the
model, shows the connected database file and when it last changed, and has **Refresh from
database** (pages cache API answers for 10 seconds; the API itself reads the database on every
request, so a rebuilt or changed database shows up without restarting anything).
