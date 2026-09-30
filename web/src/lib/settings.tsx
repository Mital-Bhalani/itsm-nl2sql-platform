// App-wide choices (dataset, model provider, model, light/dark theme), remembered in localStorage.
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark'

export type Settings = {
  dataset: string
  provider: string
  models: Record<string, string>
  theme: Theme
}

type SettingsContext = Settings & {
  setDataset: (dataset: string) => void
  setProvider: (provider: string) => void
  setModel: (provider: string, model: string) => void
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

const KEY = 'itsm-insights-settings'
const Context = createContext<SettingsContext | null>(null)

function systemTheme(): Theme {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Put the theme class on <html>. Called before the first render too, so there is no light flash. */
export function applyTheme(theme: Theme) {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

/** `?theme=dark` / `?theme=light` in the URL wins once (handy for demos and screenshots). */
function urlTheme(): Theme | undefined {
  const value = new URLSearchParams(window.location.search).get('theme')
  return value === 'dark' || value === 'light' ? value : undefined
}

export function load(): Settings {
  const defaults: Settings = { dataset: 'default', provider: '', models: {}, theme: systemTheme() }
  let settings = defaults
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? 'null')
    if (saved && typeof saved.dataset === 'string') {
      settings = { ...defaults, ...saved, theme: saved.theme === 'dark' || saved.theme === 'light' ? saved.theme : defaults.theme }
    }
  } catch {
    /* ignore corrupt storage */
  }
  return { ...settings, theme: urlTheme() ?? settings.theme }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(load)
  useEffect(() => {
    applyTheme(settings.theme)
    try {
      localStorage.setItem(KEY, JSON.stringify(settings))
    } catch {
      /* storage blocked (private mode): settings just are not remembered */
    }
  }, [settings])
  const value: SettingsContext = {
    ...settings,
    setDataset: (dataset) => setSettings((s) => ({ ...s, dataset })),
    setProvider: (provider) => setSettings((s) => ({ ...s, provider })),
    setModel: (provider, model) => setSettings((s) => ({ ...s, models: { ...s.models, [provider]: model } })),
    setTheme: (theme) => setSettings((s) => ({ ...s, theme })),
    toggleTheme: () => setSettings((s) => ({ ...s, theme: s.theme === 'dark' ? 'light' : 'dark' })),
  }
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useSettings() {
  const value = useContext(Context)
  if (!value) throw new Error('useSettings must be used inside SettingsProvider')
  return value
}
