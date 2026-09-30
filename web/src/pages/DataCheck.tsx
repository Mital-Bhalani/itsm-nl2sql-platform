import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Download, Play, XCircle } from 'lucide-react'
import { useState } from 'react'
import { useHealth } from '@/components/Layout'
import { Button, Card, CardTitle, DataTable, ErrorBox, Notice, PageHeader, Select, Spinner, Stat, downloadCsv } from '@/components/ui'
import { api, type SqlResult } from '@/lib/api'
import { useSettings } from '@/lib/settings'

const EXAMPLES: Record<string, string> = {
  'Incidents by priority': 'SELECT priority, COUNT(*) AS incidents FROM incidents GROUP BY priority',
  'Open incidents by team':
    "SELECT g.name AS team, COUNT(*) AS open_incidents\nFROM incidents i\nJOIN assignment_groups g ON g.id = i.assignment_group_id\nWHERE i.status IN ('New', 'In Progress', 'On Hold')\nGROUP BY g.name ORDER BY 2 DESC",
  'Latest 20 incidents': 'SELECT * FROM incidents ORDER BY opened_at DESC LIMIT 20',
  'Upcoming changes': "SELECT id, description, risk, status, planned_start FROM changes\nWHERE planned_start >= '2026-09-28' ORDER BY planned_start",
  'SLA targets': 'SELECT * FROM sla_targets',
}

export default function DataCheckPage() {
  const { dataset } = useSettings()
  const info = useHealth().data!.datasets[dataset]
  const reconcile = useQuery({ queryKey: ['reconcile', dataset], queryFn: () => api.reconcile(dataset), staleTime: 0 })
  const [sql, setSql] = useState(EXAMPLES['Incidents by priority'])
  const [result, setResult] = useState<SqlResult | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      setResult(await api.sql(sql, dataset))
    } catch (e) {
      setResult(null)
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader title="Data check" subtitle="Prove the UI shows what is in the database, and query the database yourself (read-only)." />
      <div className="mb-5 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Connected database" value={<span className="text-lg">{info.file}</span>} />
        <Stat label="Size" value={`${info.size_mb} MB`} />
        <Stat label="Last changed (UTC)" value={<span className="text-lg">{info.modified?.replace('T', ' ').slice(0, 16)}</span>} />
        <Stat label="Semantic catalog" value={info.catalog ? 'present' : 'missing'} />
      </div>

      <Card className="mb-5">
        <CardTitle hint="Left: what the pages show. Right: the same number computed separately on the database.">UI numbers vs the database</CardTitle>
        {reconcile.isLoading && <Spinner />}
        <ErrorBox error={reconcile.error} />
        {reconcile.data && (
          <>
            <div className="mb-3">
              {reconcile.data.passed === reconcile.data.total ? (
                <Notice tone="ok">All {reconcile.data.total} checks match the database.</Notice>
              ) : (
                <Notice tone="warn">
                  {reconcile.data.total - reconcile.data.passed} of {reconcile.data.total} checks do not match.
                </Notice>
              )}
            </div>
            <div className="max-h-96 overflow-auto rounded-xl border border-slate-200">
              <table className="min-w-full text-sm">
                <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Check</th>
                    <th className="px-3 py-2">Where shown</th>
                    <th className="px-3 py-2">Shown in UI</th>
                    <th className="px-3 py-2">In database</th>
                    <th className="px-3 py-2">Result</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {reconcile.data.checks.map((c) => (
                    <tr key={c.check} title={c.sql}>
                      <td className="px-3 py-2 text-slate-800">{c.check}</td>
                      <td className="px-3 py-2 text-slate-500">{c.where_shown}</td>
                      <td className="px-3 py-2 font-mono">{String(c.shown_in_ui)}</td>
                      <td className="px-3 py-2 font-mono">{String(c.in_database)}</td>
                      <td className="px-3 py-2">
                        {c.match ? (
                          <span className="flex items-center gap-1 text-emerald-600">
                            <CheckCircle2 className="size-4" /> match
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-red-600">
                            <XCircle className="size-4" /> differs
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-slate-500">Hover a row to see the SQL used for the database value.</p>
          </>
        )}
      </Card>

      <Card>
        <CardTitle hint="Read-only · one SELECT · LIMIT 1000 added · 5-second timeout · user names blocked">Query the database yourself</CardTitle>
        <Select label="Start from an example" onChange={(e) => setSql(EXAMPLES[e.target.value])} className="mb-3 w-72">
          {Object.keys(EXAMPLES).map((k) => (
            <option key={k}>{k}</option>
          ))}
        </Select>
        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          rows={6}
          spellCheck={false}
          className="w-full rounded-xl border border-slate-200 bg-slate-900 p-3 font-mono text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-200"
        />
        <div className="mt-3 flex items-center gap-3">
          <Button variant="primary" onClick={run} disabled={busy || !sql.trim()}>
            <Play className="size-4" /> Run query
          </Button>
          {result && (
            <>
              <span className="text-sm text-slate-500">
                {result.row_count} rows{result.truncated ? ' (capped at 1,000)' : ''}
              </span>
              <Button variant="ghost" onClick={() => downloadCsv('query.csv', result.columns, result.rows)}>
                <Download className="size-4" /> CSV
              </Button>
            </>
          )}
        </div>
        <div className="mt-3">
          <ErrorBox error={error} />
          {result && (
            <DataTable columns={result.columns} rows={result.rows.map((r) => Object.fromEntries(result.columns.map((c, i) => [c, r[i]])))} />
          )}
        </div>
      </Card>
    </>
  )
}
