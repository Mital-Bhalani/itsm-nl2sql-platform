// Typed client for the FastAPI backend. Same-origin in both dev (Vite proxy) and production
// (FastAPI serves this app at /web/), so paths are relative to the site root.

export type Provider = {
  name: string
  label: string
  default_model: string
  configured: boolean
  is_default: boolean
}

export type DatasetState = {
  path: string
  exists: boolean
  catalog: boolean
  file?: string
  size_mb?: number
  modified?: string
  error?: string
}

export type Health = {
  status: 'ok' | 'degraded'
  version: string
  as_of: string
  auth_required: boolean
  datasets: Record<string, DatasetState>
  llm_ready: boolean
  providers: Provider[]
}

export type Cell = string | number | null

/** One earlier exchange of the current Ask thread, sent back so follow-up questions have context. */
export type AskTurn = { question: string; sql: string | null }

export type AskResult = {
  question: string
  answer: string | null
  followups: string[]
  sql: string | null
  assumption: string | null
  refusal: string | null
  unsafe: string | null
  error: string | null
  terms: [string, string][]
  columns: string[]
  rows: Cell[][]
  row_count: number
  truncated: boolean
  repaired: boolean
  provider: string | null
  model: string | null
  tokens_in: number | null
  tokens_out: number | null
  timings: Record<string, number>
  request_id: string
}

export type TeamRow = {
  team: string
  incidents: number
  open: number
  resolved: number
  sla_breaches: number
  sla_breach_rate_pct: number
  mttr_hours: number | null
  reopen_rate_pct: number
}

export type MonthRow = {
  month: string
  incidents: number
  resolved: number
  sla_breaches: number
  sla_breach_rate_pct: number
  mttr_hours: number | null
  reopen_rate_pct: number
}

export type Kpis = {
  as_of: string
  headline: {
    incidents: number
    open: number
    resolved_or_closed: number
    sla_breaches: number
    sla_breach_rate_pct: number | null
    mttr_minutes: number | null
    mttr_hours: number | null
    reopen_rate_pct: number | null
  }
  by_team: TeamRow[]
  by_month: MonthRow[]
  by_priority: { priority: string; incidents: number; resolved: number; sla_breaches: number; sla_breach_rate_pct: number }[]
  by_status: { status: string; incidents: number }[]
  upcoming_changes_by_risk: { risk: string; changes: number }[]
}

export type ColumnSpec = {
  column_name: string
  data_type: string
  allowed_values: string | null
  description: string
  is_pii: number
}

export type TableSpec = {
  table_name: string
  description: string
  grain: string
  rows: number
  columns: ColumnSpec[]
}

export type TablePage = {
  table: string
  columns: string[]
  rows: Record<string, Cell>[]
  total: number
  page: number
  size: number
  pages: number
}

export type Incident = {
  id: number
  short_desc: string
  priority: number
  status: string
  assignment_group: string
  opened_at: string
  resolved_at: string | null
  reopened_count: number
  target_minutes: number
  resolution_minutes: number | null
  sla_breached: boolean | null
  sla_due_at: string
  age_minutes?: number
  past_target?: boolean
  target_used_pct: number | null
  timeline: { event: string; at: string }[]
}

export type SimilarIncident = {
  id: number
  short_desc: string
  priority: number
  status: string
  assignment_group: string
  opened_at: string
  similarity: number
}

export type ReconcileCheck = {
  check: string
  shown_in_ui: Cell
  in_database: Cell
  where_shown: string
  match: boolean
  sql: string
}

export type SqlResult = { sql: string; columns: string[]; rows: Cell[][]; row_count: number; truncated: boolean }

export type EvalResult = {
  id: string
  category: string
  question: string
  status: string
  generated_sql: string | null
  assumption: string | null
  expected_rows: Cell[][]
  actual_rows: Cell[][]
  error: string | null
}

export type EvalJob = {
  id: string
  status: 'queued' | 'running' | 'done' | 'failed'
  mode: string
  golden: string
  provider: string | null
  model: string | null
  total: number
  completed: number
  passed: number
  execution_accuracy: number | null
  error: string | null
  started_at: string
  finished_at: string | null
  results: EvalResult[]
}

export type EvalSummary = Omit<EvalJob, 'results'>

export type EvalQuestionHistory = {
  id: string
  question: string
  category: string
  runs: number
  passed: number
  pass_rate: number
  last_status: string
  failures: { job_id: string; started_at: string; status: string; error: string | null }[]
}

export type EvalHistory = { runs: EvalSummary[]; questions: EvalQuestionHistory[] }

export class ApiError extends Error {}

const API_KEY = import.meta.env.VITE_APP_API_KEY as string | undefined

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (API_KEY) headers['X-API-Key'] = API_KEY
  let response: Response
  try {
    response = await fetch(path, { ...init, headers: { ...headers, ...(init?.headers ?? {}) } })
  } catch {
    throw new ApiError('Cannot reach the API. Is it running (python run_app.py)?')
  }
  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      detail = (await response.json()).detail
    } catch {
      /* not JSON */
    }
    if (Array.isArray(detail)) {
      detail = detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join('.')}: ${d.msg}`).join('; ')
    }
    throw new ApiError(`${String(detail)} (HTTP ${response.status})`)
  }
  return response.json() as Promise<T>
}

function query(params: Record<string, string | number | boolean | null | undefined>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  health: () => request<Health>('/health'),
  overview: (dataset: string) =>
    request<{ as_of: string; row_counts: Record<string, number>; catalog_counts: Record<string, number>; incidents_from: string; incidents_to: string }>(
      `/api/overview${query({ dataset })}`,
    ),
  ask: (body: { question: string; provider?: string; model?: string; dataset: string; history?: AskTurn[] }) =>
    request<AskResult>('/api/ask', { method: 'POST', body: JSON.stringify(body) }),
  feedback: (body: { request_id: string; rating: 'up' | 'down'; question?: string }) =>
    request<{ recorded: boolean }>('/api/feedback', { method: 'POST', body: JSON.stringify(body) }),
  kpis: (params: { dataset: string; date_from?: string; date_to?: string; group_id?: number }) =>
    request<Kpis>(`/api/kpis${query(params)}`),
  groups: (dataset: string) => request<{ id: number; name: string }[]>(`/api/groups${query({ dataset })}`),
  tables: (dataset: string) => request<TableSpec[]>(`/api/tables${query({ dataset })}`),
  browse: (table: string, params: Record<string, string | number | boolean | undefined>) =>
    request<TablePage>(`/api/tables/${table}${query(params)}`),
  incident: (id: number, dataset: string) => request<Incident>(`/api/incidents/${id}${query({ dataset })}`),
  similar: (id: number, dataset: string) =>
    request<SimilarIncident[]>(`/api/incidents/${id}/similar${query({ dataset })}`),
  catalog: <T = Record<string, Cell>>(section: string, dataset: string) =>
    request<T[]>(`/api/catalog/${section}${query({ dataset })}`),
  reconcile: (dataset: string) =>
    request<{ checks: ReconcileCheck[]; passed: number; total: number }>(`/api/reconcile${query({ dataset })}`),
  sql: (sql: string, dataset: string) =>
    request<SqlResult>('/api/sql', { method: 'POST', body: JSON.stringify({ sql, dataset }) }),
  startEval: (body: { golden: string; mode: string; provider?: string; model?: string }) =>
    request<EvalJob>('/api/evals', { method: 'POST', body: JSON.stringify(body) }),
  evalJob: (id: string) => request<EvalJob>(`/api/evals/${id}`),
  listEvals: () => request<EvalSummary[]>('/api/evals'),
  evalHistory: (golden: string, limit = 20) => request<EvalHistory>(`/api/evals/history${query({ golden, limit })}`),
}
