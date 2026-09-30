// App-wide choices (dataset, model provider, model), remembered in localStorage.
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Settings = {
  dataset: string
  provider: string
  models: Record<string, string>
}

type SettingsContext = Settings & {
  setDataset: (dataset: string) => void
  setProvider: (provider: string) => void
  setModel: (provider: string, model: string) => void
}

const KEY = 'itsm-insights-settings'
const Context = createContext<SettingsContext | null>(null)

function load(): Settings {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? 'null')
    if (saved && typeof saved.dataset === 'string') return saved
  } catch {
    /* ignore corrupt storage */
  }
  return { dataset: 'default', provider: '', models: {} }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(load)
  useEffect(() => {
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
  }
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useSettings() {
  const value = useContext(Context)
  if (!value) throw new Error('useSettings must be used inside SettingsProvider')
  return value
}
