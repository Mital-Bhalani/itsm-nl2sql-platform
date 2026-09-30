import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Badge, Button, Card, CardTitle, ErrorBox, Input, Notice, PageHeader, PRIORITY_COLORS, STATUS_COLORS, Spinner, Stat } from '@/components/ui'
import { api } from '@/lib/api'
import { useSettings } from '@/lib/settings'

const EVENT_COLORS: Record<string, string> = { Opened: '#2563EB', 'SLA due': '#111827', Resolved: '#16A34A', Closed: '#4B5563' }

function Gauge({ used, targetHours, finished }: { used: number; targetHours: number; finished: boolean }) {
  const max = Math.max(150, used * 1.1)
  const color = used > 100 ? '#DC2626' : used > 80 ? '#EA580C' : '#16A34A'
  const pct = (v: number) => `${(v / max) * 100}%`
  return (
    <div>
      <div className="text-4xl font-extrabold" style={{ color }}>
        {used}%
      </div>
      <p className="mb-4 text-sm text-muted">
        of the {targetHours}-hour target used ({finished ? 'finished' : 'still running'})
      </p>
      <div className="relative h-8 overflow-hidden rounded-full">
        <div className="absolute inset-y-0 left-0 bg-tone-ok-strong" style={{ width: pct(80) }} />
        <div className="absolute inset-y-0 bg-tone-warn-strong" style={{ left: pct(80), width: pct(20) }} />
        <div className="absolute inset-y-0 right-0 bg-tone-bad-strong" style={{ left: pct(100) }} />
        <div className="absolute inset-y-2 left-0 rounded-r-full" style={{ width: pct(used), background: color }} />
        <div className="absolute inset-y-0 border-l-2 border-dashed border-ink" style={{ left: pct(100) }} />
      </div>
      <div className="mt-1 flex justify-between text-xs text-faint">
        <span>0%</span>
        <span style={{ marginLeft: pct(100) }}>target</span>
        <span>{Math.round(max)}%</span>
      </div>
    </div>
  )
}

export default function IncidentPage() {
  const { dataset } = useSettings()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const id = Number(params.get('id') ?? 1)
  const [draft, setDraft] = useState(String(id))

  const incident = useQuery({ queryKey: ['incident', dataset, id], queryFn: () => api.incident(id, dataset) })
  const similar = useQuery({ queryKey: ['similar', dataset, id], queryFn: () => api.similar(id, dataset), enabled: incident.isSuccess })
  const go = (next: number) => {
    setDraft(String(next))
    navigate(`/incident?id=${next}`)
  }

  return (
    <>
      <PageHeader title="Incident detail" subtitle="How long it took against its SLA, what happened when, and what looks similar.">
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (Number(draft) > 0) go(Number(draft))
          }}
        >
          <Input value={draft} onChange={(e) => setDraft(e.target.value)} type="number" min={1} className="w-28 text-white" />
          <Button type="submit" className="bg-white/15 text-white hover:bg-white/25">
            Open
          </Button>
        </form>
      </PageHeader>

      {incident.isLoading && <Spinner />}
      <ErrorBox error={incident.error} />
      {incident.data && (() => {
        const d = incident.data
        const verdict =
          d.resolution_minutes != null ? (d.sla_breached ? 'Breached' : 'Met') : d.age_minutes != null ? (d.past_target ? 'Past target' : 'Within target') : 'Not measured'
        return (
          <>
            <Card className="mb-5">
              <h2 className="text-xl font-bold text-ink">
                #{d.id} · {d.short_desc}
              </h2>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge color={PRIORITY_COLORS[d.priority]}>P{d.priority}</Badge>
                <Badge color={STATUS_COLORS[d.status]}>{d.status}</Badge>
                <Badge>{d.assignment_group}</Badge>
                {d.reopened_count > 0 && <Badge color="#DC2626">Reopened ×{d.reopened_count}</Badge>}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
                <Stat label="SLA target" value={`${d.target_minutes / 60} h`} />
                <Stat
                  label={d.resolution_minutes != null ? 'Time to resolve' : 'Open for'}
                  value={d.resolution_minutes != null ? `${(d.resolution_minutes / 60).toFixed(1)} h` : d.age_minutes != null ? `${(d.age_minutes / 60).toFixed(1)} h` : '—'}
                />
                <Stat label="SLA" value={<span className={verdict === 'Met' || verdict === 'Within target' ? 'text-tone-ok' : 'text-tone-bad'}>{verdict}</span>} />
                <Stat label="Opened" value={<span className="text-lg">{d.opened_at.slice(0, 16)}</span>} />
                <Stat label="SLA due" value={<span className="text-lg">{d.sla_due_at.slice(0, 16)}</span>} />
              </div>
            </Card>

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
              <Card className="lg:col-span-2">
                <CardTitle>SLA used</CardTitle>
                {d.target_used_pct == null ? (
                  <Notice>A cancelled incident has no resolution time, so no SLA is measured.</Notice>
                ) : (
                  <Gauge used={d.target_used_pct} targetHours={d.target_minutes / 60} finished={!!d.resolved_at} />
                )}
              </Card>
              <Card className="lg:col-span-3">
                <CardTitle>Timeline</CardTitle>
                <ol className="relative ml-2 border-l-2 border-line">
                  {d.timeline.map((e) => (
                    <li key={e.event} className="mb-5 ml-5">
                      <span
                        className="absolute -left-[9px] mt-1 size-4 rounded-full border-2 border-white"
                        style={{ background: EVENT_COLORS[e.event] ?? '#DC2626' }}
                      />
                      <div className="font-semibold text-ink">{e.event}</div>
                      <div className="text-sm text-muted">{e.at.slice(0, 16)} UTC</div>
                    </li>
                  ))}
                </ol>
                {d.reopened_count > 0 && (
                  <p className="text-xs text-muted">
                    Reopened {d.reopened_count} time(s); reopen dates are not stored, and the resolution time is measured to the latest resolution.
                  </p>
                )}
              </Card>
            </div>

            <Card className="mt-5">
              <CardTitle hint="Shared description words, same team and same priority">Similar incidents</CardTitle>
              {similar.isLoading && <Spinner />}
              {similar.data && similar.data.length === 0 && <p className="text-sm text-muted">No incidents share words with this description.</p>}
              <div className="divide-y divide-line-soft">
                {similar.data?.map((s) => (
                  <button key={s.id} onClick={() => go(s.id)} className="flex w-full items-center gap-4 py-2.5 text-left hover:bg-brand-soft">
                    <span className="w-14 font-mono text-sm text-muted">#{s.id}</span>
                    <span className="flex-1 text-sm text-ink">{s.short_desc}</span>
                    <Badge color={PRIORITY_COLORS[s.priority]}>P{s.priority}</Badge>
                    <Badge color={STATUS_COLORS[s.status]}>{s.status}</Badge>
                    <span className="w-40 text-xs text-muted">{s.assignment_group}</span>
                    <span className="flex w-28 items-center gap-2">
                      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
                        <span className="block h-full rounded-full bg-brand-500" style={{ width: `${Math.min(100, (s.similarity / 1.2) * 100)}%` }} />
                      </span>
                      <span className="text-xs text-muted">{s.similarity.toFixed(2)}</span>
                    </span>
                  </button>
                ))}
              </div>
            </Card>
          </>
        )
      })()}
    </>
  )
}
