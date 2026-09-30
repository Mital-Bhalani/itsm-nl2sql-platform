// Saved (pinned) questions, kept in the browser only. Newest first, no duplicates, at most 20.
import { useCallback, useEffect, useState } from 'react'

export const SAVED_KEY = 'itsm-insights-saved'
const MAX = 20
const EVENT = 'itsm-saved-changed'

function read(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(SAVED_KEY) ?? '[]')
    return Array.isArray(value) ? value.filter((q): q is string => typeof q === 'string') : []
  } catch {
    return []
  }
}

function write(list: string[]) {
  try {
    localStorage.setItem(SAVED_KEY, JSON.stringify(list))
  } catch {
    /* storage blocked: the list just is not remembered */
  }
  window.dispatchEvent(new Event(EVENT))
}

/** The saved list plus save / remove / toggle, kept in sync across components on the page. */
export function useSavedQuestions() {
  const [saved, setSaved] = useState<string[]>(read)
  useEffect(() => {
    const sync = () => setSaved(read())
    window.addEventListener(EVENT, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(EVENT, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])
  const save = useCallback((question: string) => {
    const q = question.trim()
    if (!q) return
    write([q, ...read().filter((x) => x !== q)].slice(0, MAX))
  }, [])
  const remove = useCallback((question: string) => write(read().filter((x) => x !== question)), [])
  const toggle = useCallback(
    (question: string) => (read().includes(question.trim()) ? remove(question.trim()) : save(question)),
    [remove, save],
  )
  return { saved, save, remove, toggle, isSaved: (q: string) => saved.includes(q.trim()) }
}
