# web/ — React front end ("ITSM Insights")

The front end of the platform: Home, Ask, Dashboard, Explorer, Incident, Catalog, Evals and
Data check. It talks only to the FastAPI backend.

Stack: Vite + React 19 + TypeScript, Tailwind CSS v4, TanStack Query (API caching, 10-second
freshness), React Router (hash routes), Recharts, lucide-react icons. Small shadcn-style
components live in `src/components/ui.tsx`.

**Light and dark theme.** The switch sits in the top bar, top-right corner of every page. The
choice is remembered in localStorage; the first visit follows the OS preference; `?theme=dark`
or `?theme=light` in the URL forces one (handy for screenshots). Dark mode is the `dark` class
on `<html>`, set before the first paint in `main.tsx`. Components never use raw palette shades:
`src/index.css` defines semantic tokens (`bg-surface`, `bg-surface-2`, `text-ink`, `text-muted`,
`border-line`, `bg-brand-soft`, `bg-tone-warn` …) as CSS variables with a light and a dark
value, and charts read `--chart-grid`, `--chart-tick` and the shared `TOOLTIP` style.

**Responsive.** Below the `lg` breakpoint (1024 px) the sidebar becomes a drawer opened from the
menu button in the top bar; page padding, the header band and the grids scale down; tables
scroll sideways inside their cards.

**Fast page switches.** Pages are code-split, but `src/routes.ts` prefetches every page chunk
while the browser is idle right after the first page renders, and again on hover or focus of
a sidebar link, so a click never waits for a download. Query results stay cached for 10 minutes
(`gcTime`), so returning to a page shows data at once, and each page fades in over 180 ms
(disabled under `prefers-reduced-motion`).

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
| `src/lib/settings.tsx` | dataset / provider / model / theme choice, remembered in localStorage; `applyTheme()` |
| `src/routes.ts` | page module map, `preloadPage()` / `preloadAllPages()` |
| `src/components/Layout.tsx` | top bar (menu button, page name, theme toggle), sidebar or drawer: navigation, pickers, connected database, Refresh |
| `src/index.css` | theme tokens for light and dark, page-enter animation, chart text colours |
| `src/components/AutoChart.tsx` | chart chosen from a query result (bar, or line for months) |
| `src/lib/saved.ts` | saved questions (localStorage) with a hook shared by Ask and Home |
| `src/pages/*.tsx` | one file per page |
| `e2e/`, `playwright.config.ts` | end-to-end tests (`npm run e2e`) |

Links: `#/ask?q=<question>` asks straight away; `#/explorer?table=incidents&team=Network`
opens a team's incidents; `#/incident?id=7` opens an incident.

**Ask threads, saved questions.** Each Ask thread sends its last three exchanges that produced
SQL (`history: [{question, sql}]`) with the next question, so "and by priority?" works; Clear
starts a new thread. The star on a question saves it (browser only, localStorage key
`itsm-insights-saved`, 20 most recent); saved questions appear as chips above the examples on
Ask and in a card on Home.

**Evals history.** The Evals page reads `GET /api/evals/history?golden=…` for the stored runs and
the per-question pass rate across live runs ("Flaky questions"); clicking a run loads its
per-question results from `GET /api/evals/{id}`. On an API without those endpoints the cards
show their empty state.

**End-to-end tests** (`web/e2e/`, Playwright, system Edge, no browser download):

```bash
npm run e2e                 # builds, starts the API on port 8010 from the repo root, runs, stops it
E2E_PORT=8000 npm run e2e   # against an API you already started (python run_app.py)
```

They cover every page in both themes with no console errors, the theme toggle (position,
switching, persistence), the phone drawer (open, Escape, focus return), instant page switches
(the chunk spinner never shows after the first page), saved questions and the Evals history
cards. They never submit a question, so no model credit is used.

Gotchas found while testing: effects must not return values (newer Chromium returns a
Promise from `scrollIntoView`, which React then calls as a cleanup and crashes); chart
animations are off because they never finish in headless screenshots.
