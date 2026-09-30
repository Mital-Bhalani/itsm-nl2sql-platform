// One place for the page modules, shared by the router (lazy routes) and the sidebar
// (prefetch on hover and in idle time, so switching pages never waits for a download).
import type { ComponentType } from 'react'

export type PageModule = { default: ComponentType }

export const PAGES: Record<string, () => Promise<PageModule>> = {
  '/': () => import('@/pages/Home'),
  '/ask': () => import('@/pages/Ask'),
  '/dashboard': () => import('@/pages/Dashboard'),
  '/explorer': () => import('@/pages/Explorer'),
  '/incident': () => import('@/pages/Incident'),
  '/catalog': () => import('@/pages/Catalog'),
  '/evals': () => import('@/pages/Evals'),
  '/data-check': () => import('@/pages/DataCheck'),
}

const loaded = new Map<string, Promise<PageModule>>()

/** Start (or reuse) the download of one page's code. */
export function preloadPage(path: string) {
  const loader = PAGES[path]
  if (!loader) return Promise.resolve(undefined)
  let promise = loaded.get(path)
  if (!promise) {
    promise = loader()
    loaded.set(path, promise)
  }
  return promise
}

/** After the first page is up, fetch the rest while the browser is idle. */
export function preloadAllPages() {
  const run = () => Object.keys(PAGES).forEach((path) => void preloadPage(path))
  const idle = (window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => void }).requestIdleCallback
  if (idle) idle(run, { timeout: 2000 })
  else setTimeout(run, 300)
}
