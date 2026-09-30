import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy } from 'react'
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from '@/components/Layout'
import { SettingsProvider } from '@/lib/settings'
import { preloadPage } from '@/routes'

// lazy() goes through preloadPage so a chunk fetched by the sidebar prefetch is reused here.
const page = (path: string) => lazy(() => preloadPage(path) as Promise<{ default: React.ComponentType }>)
const HomePage = page('/')
const AskPage = page('/ask')
const DashboardPage = page('/dashboard')
const ExplorerPage = page('/explorer')
const IncidentPage = page('/incident')
const CatalogPage = page('/catalog')
const EvalsPage = page('/evals')
const DataCheckPage = page('/data-check')

// Data is re-read from the API after 10 seconds; the sidebar's "Refresh from database" button
// forces it immediately. Cached answers are kept for 10 minutes, so returning to a page is instant.
const client = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, gcTime: 10 * 60_000, retry: 1, refetchOnWindowFocus: true } },
})

export default function App() {
  return (
    <QueryClientProvider client={client}>
      <SettingsProvider>
        <HashRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<HomePage />} />
              <Route path="ask" element={<AskPage />} />
              <Route path="dashboard" element={<DashboardPage />} />
              <Route path="explorer" element={<ExplorerPage />} />
              <Route path="incident" element={<IncidentPage />} />
              <Route path="catalog" element={<CatalogPage />} />
              <Route path="evals" element={<EvalsPage />} />
              <Route path="data-check" element={<DataCheckPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </HashRouter>
      </SettingsProvider>
    </QueryClientProvider>
  )
}
