import { Play } from 'lucide-react'
import { useState } from 'react'
import { useModel } from '@/components/Layout'
import { Badge, Button, Card, CardTitle, ErrorBox, PageHeader, Select } from '@/components/ui'
import { api, type EvalJob } from '@/lib/api'

const STATUS: Record<string, [string, string]> = {
  pass: ['pass', '#16A34A'],
  wrong_result: ['wrong result', '#DC2626'],
  sql_error: ['SQL error', '#EA580C'],
  unsafe: ['unsafe', '#7C3AED'],
  no_sql: ['no SQL', '#64748B'],
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export default function EvalsPage() {
  const { provider, model } = useModel()
  const [golden, setGolden] = useState('golden_set.yaml')
  const [mode, setMode] = useState('self-test')
  const [runs, setRuns] = useState<EvalJob[]>([])
  const [running, setRunning] = useState<EvalJob | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [open, setOpen] = useState<string | null>(null)

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
      setRuns((r) => [...r, job])
    } catch (e) {
      setError(e)
    } finally {
      setRunning(null)
    }
  }
  const latest = runs[runs.length - 1]

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
        <div className="pb-2 text-sm text-slate-600">
          Live model: <b>{provider?.name} / {model}</b> <span className="text-xs text-slate-400">(change in the sidebar)</span>
        </div>
        <Button variant="primary" onClick={run} disabled={!!running} className="ml-auto">
          <Play className="size-4" /> Run evaluation
        </Button>
      </Card>
      <ErrorBox error={error} />
      {running && (
        <Card className="mb-5">
          <div className="mb-2 text-sm text-slate-600">
            {running.completed} / {running.total} questions · {running.passed} passed
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full bg-brand-600 transition-all" style={{ width: `${running.total ? (running.completed / running.total) * 100 : 0}%` }} />
          </div>
        </Card>
      )}

      {runs.length > 0 && (
        <Card className="mb-5">
          <CardTitle>Runs this session</CardTitle>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-1.5">Started</th>
                <th>Golden set</th>
                <th>Mode</th>
                <th>Model</th>
                <th>Passed</th>
                <th>Accuracy</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {runs.map((r) => (
                <tr key={r.id}>
                  <td className="py-2">{r.started_at.replace('T', ' ').slice(0, 19)}</td>
                  <td>{r.golden}</td>
                  <td>{r.mode}</td>
                  <td>{r.provider ? `${r.provider} / ${r.model}` : '(reference SQL)'}</td>
                  <td>
                    {r.passed} / {r.total}
                  </td>
                  <td className="font-semibold">{r.execution_accuracy != null ? `${(r.execution_accuracy * 100).toFixed(1)}%` : r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {latest && (
        <Card>
          <CardTitle>Latest run, per question</CardTitle>
          {latest.error && <ErrorBox error={latest.error} />}
          <div className="divide-y divide-slate-100">
            {latest.results.map((r) => {
              const [label, color] = STATUS[r.status] ?? [r.status, '#64748B']
              return (
                <div key={r.id} className="py-2">
                  <button onClick={() => setOpen(open === r.id ? null : r.id)} className="flex w-full items-center gap-3 text-left">
                    <span className="w-12 font-mono text-xs text-slate-500">{r.id}</span>
                    <Badge color={color}>{label}</Badge>
                    <span className="text-xs text-slate-400">{r.category}</span>
                    <span className="flex-1 text-sm text-slate-800">{r.question}</span>
                  </button>
                  {open === r.id && (
                    <div className="mt-2 grid grid-cols-1 gap-3 pl-14 lg:grid-cols-2">
                      {r.generated_sql && <pre className="overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-xs text-slate-100 lg:col-span-2">{r.generated_sql}</pre>}
                      {r.error && <p className="text-xs text-red-600 lg:col-span-2">{r.error}</p>}
                      <div>
                        <div className="text-xs font-semibold text-slate-500">Expected rows</div>
                        <pre className="text-xs">{JSON.stringify(r.expected_rows)}</pre>
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-slate-500">Actual rows</div>
                        <pre className="text-xs">{JSON.stringify(r.actual_rows)}</pre>
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
