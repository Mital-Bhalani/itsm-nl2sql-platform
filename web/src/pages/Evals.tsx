import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Play } from 'lucide-react'
import { useState } from 'react'
import { useModel } from '@/components/Layout'
import { Badge, Button, Card, CardTitle, ErrorBox, PageHeader, Select, cn } from '@/components/ui'
import { ApiError, api, type EvalHistory, type EvalJob, type EvalSummary } from '@/lib/api'

const STATUS: Record<string, [string, string]> = {
  pass: ['pass', '#16A34A'],
  wrong_result: ['wrong result', '#DC2626'],
  sql_error: ['SQL error', '#EA580C'],
  unsafe: ['unsafe', '#7C3AED'],
  no_sql: ['no SQL', '#64748B'],
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const when = (iso: string) => iso.replace('T', ' ').slice(0, 16)
const pct = (v: number | null | undefined) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)

/** History endpoints may not exist yet (older API): treat a 404 as "no history". */
async function tolerant<T>(call: () => Promise<T>, empty: T): Promise<T> {
  try {
    return await call()
  } catch (e) {
    if (e instanceof ApiError && /HTTP 404|HTTP 405/.test(e.message)) return empty
    throw e
  }
}

export default function EvalsPage() {
  const { provider, model } = useModel()
  const client = useQueryClient()
  const [golden, setGolden] = useState('golden_set.yaml')
  const [mode, setMode] = useState('self-test')
  const [running, setRunning] = useState<EvalJob | null>(null)
  const [selected, setSelected] = useState<EvalJob | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [openFlaky, setOpenFlaky] = useState<string | null>(null)

  const history = useQuery({
    queryKey: ['eval-history', golden],
    queryFn: () => tolerant<EvalHistory>(() => api.evalHistory(golden, 20), { runs: [], questions: [] }),
  })
  const jobs = useQuery({
    queryKey: ['eval-jobs'],
    queryFn: () => tolerant<EvalSummary[]>(() => api.listEvals(), []),
  })
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ['eval-history'] })
    void client.invalidateQueries({ queryKey: ['eval-jobs'] })
  }

  const run = async () => {
    setError(null)
    try {
      let job = await api.startEval({ golden, mode, ...(mode === 'live' ? { provider: provider?.name, model } : {}) })
      setRunning(job)
      while (job.status === 'queued' || job.status === 'running') {
        await sleep(1000)
        job = await api.evalJob(job.id)
        setRunning(job)
      }
      setSelected(job)
    } catch (e) {
      setError(e)
    } finally {
      setRunning(null)
      refresh()
    }
  }

  const load = async (id: string) => {
    setError(null)
    try {
      setSelected(await api.evalJob(id))
      setOpen(null)
    } catch (e) {
      setError(e)
    }
  }

  // Runs for the selected golden set: the history endpoint when it exists, else the job list.
  const runs: EvalSummary[] = (history.data?.runs.length ? history.data.runs : (jobs.data ?? [])).filter((r) => r.golden === golden)
  const flaky = (history.data?.questions ?? []).filter((q) => q.pass_rate < 1)
  const liveRuns = runs.filter((r) => r.mode === 'live' && r.status === 'done').length

  return (
    <>
      <PageHeader
        title="Evaluation"
        subtitle="Score the agent against the golden set: the SQL must return the same rows as the reference. Self-test is free; live runs use API credits."
      />
      <Card className="mb-5 flex flex-wrap items-end gap-4">
        <Select label="Golden set" value={golden} onChange={(e) => setGolden(e.target.value)}>
          <option>golden_set.yaml</option>
          <option>golden_set_large.yaml</option>
        </Select>
        <Select label="Mode" value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="self-test">self-test (reference SQL, no API)</option>
          <option value="live">live (calls the model)</option>
        </Select>
        <div className="pb-2 text-sm text-ink-2">
          Live model: <b>{provider?.name} / {model}</b> <span className="text-xs text-faint">(change in the sidebar)</span>
        </div>
        <Button variant="primary" onClick={run} disabled={!!running} className="ml-auto">
          <Play className="size-4" /> Run evaluation
        </Button>
      </Card>
      <ErrorBox error={error} />
      <ErrorBox error={history.error} />
      {running && (
        <Card className="mb-5">
          <div className="mb-2 text-sm text-ink-2">
            {running.completed} / {running.total} questions · {running.passed} passed
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-3">
            <div className="h-full bg-brand-600 transition-all" style={{ width: `${running.total ? (running.completed / running.total) * 100 : 0}%` }} />
          </div>
        </Card>
      )}

      <div className="mb-5 grid grid-cols-1 gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2" data-testid="recent-runs">
          <CardTitle hint={runs.length ? `${runs.length} stored run${runs.length === 1 ? '' : 's'} · click one to see its questions` : undefined}>
            Recent runs
          </CardTitle>
          {runs.length === 0 ? (
            <p className="py-4 text-sm text-muted">
              No runs stored for {golden} yet. Run a self-test (free) or a live evaluation to start the history.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-muted">
                  <tr>
                    <th className="py-1.5">When (UTC)</th>
                    <th>Mode</th>
                    <th>Model</th>
                    <th>Passed</th>
                    <th>Accuracy</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line-soft">
                  {runs.map((r) => (
                    <tr
                      key={r.id}
                      onClick={() => load(r.id)}
                      className={cn('cursor-pointer hover:bg-brand-soft', selected?.id === r.id && 'bg-brand-soft')}
                    >
                      <td className="py-2">{when(r.started_at)}</td>
                      <td>{r.mode}</td>
                      <td>{r.provider ? `${r.provider} / ${r.model}` : '(reference SQL)'}</td>
                      <td>
                        {r.passed} / {r.total}
                      </td>
                      <td className={cn('font-semibold', r.status === 'failed' && 'text-tone-bad')}>
                        {r.status === 'done' ? pct(r.execution_accuracy) : r.status}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card data-testid="flaky-questions">
          <CardTitle hint={liveRuns ? `across ${liveRuns} live run${liveRuns === 1 ? '' : 's'}` : undefined}>Flaky questions</CardTitle>
          {history.data?.questions.length === 0 || !history.data ? (
            <p className="py-4 text-sm text-muted">No live runs stored yet, so nothing to compare.</p>
          ) : flaky.length === 0 ? (
            <p className="py-4 text-sm text-tone-ok">Every question passed in every stored live run.</p>
          ) : (
            <div className="divide-y divide-line-soft">
              {flaky.map((q) => (
                <div key={q.id} className="py-2">
                  <button onClick={() => setOpenFlaky(openFlaky === q.id ? null : q.id)} className="flex w-full items-start gap-2 text-left">
                    {openFlaky === q.id ? <ChevronDown className="mt-0.5 size-4 shrink-0 text-muted" /> : <ChevronRight className="mt-0.5 size-4 shrink-0 text-muted" />}
                    <span className="w-10 shrink-0 font-mono text-xs text-muted">{q.id}</span>
                    <span className="flex-1 text-sm text-ink">{q.question}</span>
                    <span className="shrink-0 text-xs font-semibold text-tone-warn">
                      {q.passed}/{q.runs}
                    </span>
                    <Badge color={STATUS[q.last_status]?.[1] ?? '#64748B'}>{STATUS[q.last_status]?.[0] ?? q.last_status}</Badge>
                  </button>
                  {openFlaky === q.id && (
                    <ul className="mt-2 space-y-1 pl-6 text-xs text-ink-2">
                      {q.failures.map((f) => (
                        <li key={f.job_id + f.started_at}>
                          <span className="text-muted">{when(f.started_at)}</span> · {STATUS[f.status]?.[0] ?? f.status}
                          {f.error && <span className="text-tone-bad"> · {f.error}</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {selected && (
        <Card data-testid="run-results">
          <CardTitle hint={`${when(selected.started_at)} · ${selected.mode}${selected.provider ? ` · ${selected.provider} / ${selected.model}` : ''}`}>
            Run {selected.id}: {selected.passed} / {selected.total} passed
          </CardTitle>
          {selected.error && <ErrorBox error={selected.error} />}
          <div className="divide-y divide-line-soft">
            {selected.results.map((r) => {
              const [label, color] = STATUS[r.status] ?? [r.status, '#64748B']
              return (
                <div key={r.id} className="py-2">
                  <button onClick={() => setOpen(open === r.id ? null : r.id)} className="flex w-full items-center gap-3 text-left">
                    <span className="w-12 font-mono text-xs text-muted">{r.id}</span>
                    <Badge color={color}>{label}</Badge>
                    <span className="hidden text-xs text-faint sm:inline">{r.category}</span>
                    <span className="flex-1 text-sm text-ink">{r.question}</span>
                  </button>
                  {open === r.id && (
                    <div className="mt-2 grid grid-cols-1 gap-3 pl-0 sm:pl-14 lg:grid-cols-2">
                      {r.generated_sql && <pre className="overflow-auto rounded-lg bg-code p-3 font-mono text-xs text-code-ink lg:col-span-2">{r.generated_sql}</pre>}
                      {r.error && <p className="text-xs text-tone-bad lg:col-span-2">{r.error}</p>}
                      <div>
                        <div className="text-xs font-semibold text-muted">Expected rows</div>
                        <pre className="overflow-auto text-xs">{JSON.stringify(r.expected_rows)}</pre>
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-muted">Actual rows</div>
                        <pre className="overflow-auto text-xs">{JSON.stringify(r.actual_rows)}</pre>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </Card>
      )}
    </>
  )
}
