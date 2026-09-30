import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy } from 'react'
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from '@/components/Layout'
import { SettingsProvider } from '@/lib/settings'

const AskPage = lazy(() => import('@/pages/Ask'))
const CatalogPage = lazy(() => import('@/pages/Catalog'))
const DashboardPage = lazy(() => import('@/pages/Dashboard'))
const DataCheckPage = lazy(() => import('@/pages/DataCheck'))
const EvalsPage = lazy(() => import('@/pages/Evals'))
const ExplorerPage = lazy(() => import('@/pages/Explorer'))
const HomePage = lazy(() => import('@/pages/Home'))
const IncidentPage = lazy(() => import('@/pages/Incident'))

// Data is re-read from the API after 10 seconds, matching the Streamlit UI; the sidebar's
// "Refresh from database" button forces it immediately.
const client = new QueryClient({ defaultOptions: { queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: true } } })

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
