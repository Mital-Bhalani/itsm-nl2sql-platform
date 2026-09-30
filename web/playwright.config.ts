import { defineConfig } from '@playwright/test'

// End-to-end tests against the built app (web/dist) served by the real API on port 8010.
// `npm run e2e` builds first (pree2e), starts uvicorn from the repo root, runs, and stops it.
// No language model is ever called: the tests never submit a question.
// E2E_PORT=8000 runs against an API you already started (reuseExistingServer).
const PORT = Number(process.env.E2E_PORT ?? 8010)

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  workers: process.env.CI ? 2 : 4, // one shared API process; too many workers slow it down
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}/web/`,
    channel: 'msedge', // installed system browser, no download
    colorScheme: 'light',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `python -B -m uvicorn api.main:app --host 127.0.0.1 --port ${PORT}`,
    cwd: '..',
    url: `http://127.0.0.1:${PORT}/health`,
    reuseExistingServer: true,
    timeout: 60_000,
    env: { PYTHONDONTWRITEBYTECODE: '1', AUDIT_LOG: 'logs/audit-e2e.jsonl' },
  },
})
