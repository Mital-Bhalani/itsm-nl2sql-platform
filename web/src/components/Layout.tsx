import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookOpen,
  CheckCircle2,
  Database,
  FolderSearch,
  LayoutDashboard,
  Menu,
  MessageSquare,
  Moon,
  RefreshCw,
  ScanSearch,
  Sun,
  Ticket,
  Home,
  X,
} from 'lucide-react'
import { Suspense, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { api } from '@/lib/api'
import { useSettings } from '@/lib/settings'
import { preloadAllPages, preloadPage } from '@/routes'
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

/** Light/dark switch. Lives in the top bar, so it is in the top-right corner of every page. */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggleTheme } = useSettings()
  const dark = theme === 'dark'
  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
      title={dark ? 'Light theme' : 'Dark theme'}
      data-testid="theme-toggle"
      onClick={toggleTheme}
      className={cn(
        'relative inline-flex h-8 w-15 shrink-0 items-center rounded-full border border-line bg-surface-3 p-0.5 transition-colors',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-ring',
        className,
      )}
    >
      <Sun className={cn('absolute left-2 size-3.5 transition-opacity', dark ? 'opacity-40 text-muted' : 'opacity-0')} />
      <Moon className={cn('absolute right-2 size-3.5 transition-opacity', dark ? 'opacity-0' : 'opacity-40 text-muted')} />
      <span
        className={cn(
          'relative z-10 flex size-7 items-center justify-center rounded-full bg-surface text-ink shadow-sm transition-transform duration-200',
          dark ? 'translate-x-7' : 'translate-x-0',
        )}
      >
        {dark ? <Moon className="size-4 text-brand-text" /> : <Sun className="size-4 text-amber-500" />}
      </span>
    </button>
  )
}

export default function Layout() {
  const settings = useSettings()
  const health = useHealth()
  const { provider, model, providers } = useModel()
  const client = useQueryClient()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)

  const ready = Object.entries(health.data?.datasets ?? {}).filter(([, d]) => d.exists && d.catalog)
  useEffect(() => {
    if (ready.length && !ready.some(([name]) => name === settings.dataset)) settings.setDataset(ready[0][0])
  }, [ready, settings])
  const info = health.data?.datasets[settings.dataset]

  // Fetch every page's code once the shell is up, so later page switches are instant.
  useEffect(() => {
    preloadAllPages()
  }, [])
  // Close the mobile drawer after navigating.
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])
  // No page scroll under the open drawer.
  useEffect(() => {
    document.body.style.overflow = menuOpen ? 'hidden' : ''
    return () => {
      document.body.style.overflow = ''
    }
  }, [menuOpen])
  // Keyboard: focus moves into the drawer when it opens, Tab stays inside it, Escape closes it,
  // and focus goes back to the menu button when it closes.
  const menuButton = useRef<HTMLButtonElement>(null)
  const drawer = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!menuOpen) return
    const focusable = () =>
      Array.from(
        drawer.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      )
    focusable()[0]?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        setMenuOpen(false)
        return
      }
      if (e.key !== 'Tab') return
      const items = focusable()
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement as HTMLElement | null
      if (e.shiftKey && (active === first || !drawer.current?.contains(active))) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && (active === last || !drawer.current?.contains(active))) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      menuButton.current?.focus()
    }
  }, [menuOpen])

  const current = NAV.find((n) => (n.to === '/' ? location.pathname === '/' : location.pathname.startsWith(n.to)))

  const sidebar = (
    <>
      <div className="flex items-center justify-between px-2">
        <div className="flex items-center gap-2">
          <img src="./favicon.svg" alt="" className="size-9" />
          <div>
            <div className="text-base font-extrabold tracking-tight text-ink">ITSM Insights</div>
            <div className="text-[11px] text-muted">NL2SQL over ticket data</div>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setMenuOpen(false)}
          aria-label="Close menu"
          className="rounded-lg p-1.5 text-muted hover:bg-surface-3 lg:hidden"
        >
          <X className="size-5" />
        </button>
      </div>
      <nav className="flex flex-col gap-0.5">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onMouseEnter={() => void preloadPage(to)}
            onFocus={() => void preloadPage(to)}
            onTouchStart={() => void preloadPage(to)}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive ? 'bg-brand-soft text-brand-text' : 'text-ink-2 hover:bg-surface-3',
              )
            }
          >
            <Icon className="size-4" /> {label}
          </NavLink>
        ))}
      </nav>

      <div className="flex flex-col gap-3 border-t border-line-soft pt-4">
        <Select label="Dataset" value={settings.dataset} onChange={(e) => settings.setDataset(e.target.value)}>
          {ready.map(([name]) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </Select>
        <Select label="Model provider" value={provider?.name ?? ''} onChange={(e) => settings.setProvider(e.target.value)}>
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
          <p className="rounded-lg bg-tone-warn px-3 py-2 text-xs text-tone-warn">
            No API key for {provider.label}. Add it to .env and restart the API.
          </p>
        )}
      </div>

      <div className="mt-auto flex flex-col gap-2 border-t border-line-soft pt-4 text-xs text-muted">
        {info?.file && (
          <div className="flex items-start gap-2">
            <Database className="mt-0.5 size-3.5" />
            <span>
              <b className="text-ink-2">{info.file}</b> · {info.size_mb} MB
              <br />
              changed {info.modified?.replace('T', ' ').slice(0, 16)} UTC
            </span>
          </div>
        )}
        <button
          onClick={() => client.invalidateQueries()}
          className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-left font-medium text-brand-text hover:bg-brand-soft"
        >
          <RefreshCw className="size-3.5" /> Refresh from database
        </button>
        <span>Data as of {health.data?.as_of ?? '…'}</span>
      </div>
    </>
  )

  return (
    <div className="flex min-h-full">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col gap-6 overflow-y-auto border-r border-line bg-surface px-4 py-5 lg:flex">
        {sidebar}
      </aside>

      {/* Mobile drawer */}
      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMenuOpen(false)} />
          <aside
            ref={drawer}
            aria-label="Navigation"
            data-testid="drawer"
            className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col gap-6 overflow-y-auto border-r border-line bg-surface px-4 py-5 shadow-2xl"
          >
            {sidebar}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar: menu button on small screens, page name, theme toggle top right on every page */}
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-surface/80 px-4 backdrop-blur sm:px-6 lg:px-8">
          <button
            ref={menuButton}
            type="button"
            onClick={() => setMenuOpen(true)}
            aria-label="Open menu"
            aria-expanded={menuOpen}
            className="rounded-lg p-2 text-ink-2 hover:bg-surface-3 lg:hidden"
          >
            <Menu className="size-5" />
          </button>
          <img src="./favicon.svg" alt="" className="size-7 lg:hidden" />
          <div className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">
            <span className="lg:hidden">ITSM Insights</span>
            <span className="hidden text-muted lg:inline">{current?.label ?? 'ITSM Insights'}</span>
          </div>
          {info?.file && (
            <span className="hidden items-center gap-1.5 text-xs text-muted md:inline-flex">
              <Database className="size-3.5" /> {settings.dataset}
            </span>
          )}
          <ThemeToggle />
        </header>

        <main className="min-w-0 flex-1 px-4 py-4 sm:px-6 sm:py-6 lg:px-8">
          {health.isLoading && <Spinner label="Connecting to the API…" />}
          {health.error && <ErrorBox error={health.error} />}
          {health.data && ready.length === 0 && (
            <ErrorBox error="No dataset is ready. Run: python db/seed.py && python semantics/build_catalog.py" />
          )}
          {health.data && ready.length > 0 && (
            <Suspense fallback={<Spinner label="Loading page…" />}>
              <div key={location.pathname} className="animate-page">
                <Outlet />
              </div>
            </Suspense>
          )}
        </main>
      </div>
    </div>
  )
}
