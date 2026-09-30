# web/ — React front end ("ITSM Insights")

A second front end with the same features as the Streamlit UI (`ui/`): Home, Ask, Dashboard,
Explorer, Incident, Catalog, Evals and Data check. It talks only to the FastAPI backend.

Stack: Vite + React 19 + TypeScript, Tailwind CSS v4, TanStack Query (API caching, 10-second
freshness), React Router (hash routes), Recharts, lucide-react icons. Small shadcn-style
components live in `src/components/ui.tsx`.

Needs Node.js 20+ (installed: 24 LTS).

```bash
cd web
npm install          # once
npm run build        # -> web/dist, served by the API at http://127.0.0.1:8000/web/
npm run dev          # live-reload dev server at http://localhost:5173 (proxies /api to :8000)
```

`python run_app.py` prints the React URL when `web/dist` exists. `node_modules/` and `dist/`
are gitignored.

| file | purpose |
|---|---|
| `src/lib/api.ts` | typed API client; sends `X-API-Key` when `VITE_APP_API_KEY` is set at build time (it is then visible in the browser bundle, so only for internal use) |
| `src/lib/settings.tsx` | dataset / provider / model choice, remembered in localStorage |
| `src/components/Layout.tsx` | sidebar: navigation, pickers, connected database, Refresh |
| `src/components/AutoChart.tsx` | chart chosen from a query result (bar, or line for months) |
| `src/pages/*.tsx` | one file per page |

Links: `#/ask?q=<question>` asks straight away; `#/explorer?table=incidents&team=Network`
opens a team's incidents; `#/incident?id=7` opens an incident.

Gotchas found while testing: effects must not return values (newer Chromium returns a
Promise from `scrollIntoView`, which React then calls as a cleanup and crashes); chart
animations are off because they never finish in headless screenshots.
