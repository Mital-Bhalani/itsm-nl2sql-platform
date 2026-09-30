import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookOpen,
  CheckCircle2,
  Database,
  FolderSearch,
  LayoutDashboard,
  MessageSquare,
  RefreshCw,
  ScanSearch,
  Ticket,
  Home,
} from 'lucide-react'
import { Suspense, useEffect } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '@/lib/api'
import { useSettings } from '@/lib/settings'
import { ErrorBox, Input, Select, Spinner, cn } from './ui'

const NAV = [
  { to: '/', label: 'Home', icon: Home },
  { to: '/ask', label: 'Ask', icon: MessageSquare },
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/explorer', label: 'Explorer', icon: FolderSearch },
  { to: '/incident', label: 'Incident', icon: Ticket },
  { to: '/catalog', label: 'Catalog', icon: BookOpen },
  { to: '/evals', label: 'Evals', icon: CheckCircle2 },
  { to: '/data-check', label: 'Data check', icon: ScanSearch },
]

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000 })
}

/** The provider and model the user picked, falling back to the API's defaults. */
export function useModel() {
  const { provider, models } = useSettings()
  const { data } = useHealth()
  const providers = data?.providers ?? []
  const chosen =
    providers.find((p) => p.name === provider) ??
    providers.find((p) => p.is_default && p.configured) ??
    providers.find((p) => p.configured) ??
    providers[0]
  return { provider: chosen, model: chosen ? models[chosen.name] || chosen.default_model : undefined, providers }
}

export default function Layout() {
  const settings = useSettings()
  const health = useHealth()
  const { provider, model, providers } = useModel()
  const client = useQueryClient()

  const ready = Object.entries(health.data?.datasets ?? {}).filter(([, d]) => d.exists && d.catalog)
  useEffect(() => {
    if (ready.length && !ready.some(([name]) => name === settings.dataset)) settings.setDataset(ready[0][0])
  }, [ready, settings])
  const info = health.data?.datasets[settings.dataset]

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col gap-6 overflow-y-auto border-r border-slate-200 bg-white px-4 py-5">
        <div className="flex items-center gap-2 px-2">
          <img src="./favicon.svg" alt="" className="size-9" />
          <div>
            <div className="text-base font-extrabold tracking-tight text-slate-900">ITSM Insights</div>
            <div className="text-[11px] text-slate-500">NL2SQL over ticket data</div>
          </div>
        </div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition',
                  isActive ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-50',
                )
              }
            >
              <Icon className="size-4" /> {label}
            </NavLink>
          ))}
        </nav>

        <div className="flex flex-col gap-3 border-t border-slate-100 pt-4">
          <Select label="Dataset" value={settings.dataset} onChange={(e) => settings.setDataset(e.target.value)}>
            {ready.map(([name]) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </Select>
          <Select
            label="Model provider"
            value={provider?.name ?? ''}
            onChange={(e) => settings.setProvider(e.target.value)}
          >
            {providers.map((p) => (
              <option key={p.name} value={p.name}>
                {p.label}
                {p.configured ? '' : ' (no key)'}
              </option>
            ))}
          </Select>
          {provider && (
            <Input label="Model" value={model ?? ''} onChange={(e) => settings.setModel(provider.name, e.target.value)} />
          )}
          {provider && !provider.configured && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
              No API key for {provider.label}. Add it to .env and restart the API.
            </p>
          )}
        </div>

        <div className="mt-auto flex flex-col gap-2 border-t border-slate-100 pt-4 text-xs text-slate-500">
          {info?.file && (
            <div className="flex items-start gap-2">
              <Database className="mt-0.5 size-3.5" />
              <span>
                <b className="text-slate-700">{info.file}</b> · {info.size_mb} MB
                <br />
                changed {info.modified?.replace('T', ' ').slice(0, 16)} UTC
              </span>
            </div>
          )}
          <button
            onClick={() => client.invalidateQueries()}
            className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-left font-medium text-brand-700 hover:bg-brand-50"
          >
            <RefreshCw className="size-3.5" /> Refresh from database
          </button>
          <span>Data as of {health.data?.as_of ?? '…'}</span>
        </div>
      </aside>

      <main className="min-w-0 flex-1 px-8 py-6">
        {health.isLoading && <Spinner label="Connecting to the API…" />}
        {health.error && <ErrorBox error={health.error} />}
        {health.data && ready.length === 0 && (
          <ErrorBox error="No dataset is ready. Run: python db/seed.py && python semantics/build_catalog.py" />
        )}
        {health.data && ready.length > 0 && (
          <Suspense fallback={<Spinner />}>
            <Outlet />
          </Suspense>
        )}
      </main>
    </div>
  )
}
