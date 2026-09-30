import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell as ChartCell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Card, CardTitle, ErrorBox, Input, PageHeader, RISK_COLORS, STATUS_COLORS, Select, Spinner, Stat, PRIORITY_COLORS } from '@/components/ui'
import { api, type Kpis, type MonthRow } from '@/lib/api'
import { useSettings } from '@/lib/settings'

function shiftDays(iso: string, days: number) {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

function daysBetween(from: string, to: string) {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000) + 1
}

type Comparable = Pick<MonthRow, 'incidents' | 'sla_breaches' | 'sla_breach_rate_pct' | 'mttr_hours' | 'reopen_rate_pct'>

export default function DashboardPage() {
  const { dataset } = useSettings()
  const navigate = useNavigate()
  const [useDates, setUseDates] = useState(false)
  const [from, setFrom] = useState('2026-08-01')
  const [to, setTo] = useState('2026-08-31')
  const [groupId, setGroupId] = useState<number | undefined>()
  const [measure, setMeasure] = useState<'sla_breaches' | 'sla_breach_rate_pct'>('sla_breaches')

  const groups = useQuery({ queryKey: ['groups', dataset], queryFn: () => api.groups(dataset) })
  const params = { dataset, group_id: groupId, ...(useDates ? { date_from: from, date_to: to } : {}) }
  const kpis = useQuery({ queryKey: ['kpis', params], queryFn: () => api.kpis(params) })
  const days = useDates ? daysBetween(from, to) : 0
  const prevParams = useDates ? { dataset, group_id: groupId, date_from: shiftDays(from, -days), date_to: shiftDays(from, -1) } : null
  const previous = useQuery({ queryKey: ['kpis', prevParams], queryFn: () => api.kpis(prevParams!), enabled: !!prevParams })

  if (kpis.isLoading) return <Spinner />
  if (kpis.error) return <ErrorBox error={kpis.error} />
  const data = kpis.data as Kpis
  const h = data.headline
  const months = data.by_month

  let current: Comparable | null = null
  let prior: Comparable | null = null
  let note = ''
  if (useDates && previous.data) {
    current = { ...h, mttr_hours: h.mttr_hours, sla_breach_rate_pct: h.sla_breach_rate_pct ?? 0, reopen_rate_pct: h.reopen_rate_pct ?? 0 }
    const p = previous.data.headline
    prior = { ...p, sla_breach_rate_pct: p.sla_breach_rate_pct ?? 0, reopen_rate_pct: p.reopen_rate_pct ?? 0 }
    note = `vs previous ${days} days`
  } else if (!useDates) {
    const full = months.filter((m) => m.month < data.as_of.slice(0, 7))
    if (full.length >= 2) {
      current = full[full.length - 1]
      prior = full[full.length - 2]
      note = `${full[full.length - 1].month} vs ${full[full.length - 2].month}`
    }
  }
  const delta = (key: keyof Comparable) =>
    current && prior && current[key] != null && prior[key] != null ? Number(current[key]) - Number(prior[key]) : null
  const spark = (key: keyof MonthRow) => months.map((m) => Number(m[key] ?? 0))
  const openTeam = (team: string) => navigate(`/explorer?table=incidents&team=${encodeURIComponent(team)}`)

  return (
    <>
      <PageHeader title="Service dashboard" subtitle="SLA performance, workload and change risk across every team." />

      <Card className="mb-5 flex flex-wrap items-end gap-4">
        <label className="flex items-center gap-2 pb-2 text-sm font-medium text-slate-700">
          <input type="checkbox" checked={useDates} onChange={(e) => setUseDates(e.target.checked)} className="size-4 accent-brand-600" />
          Filter by date opened
        </label>
        <Input label="From" type="date" value={from} disabled={!useDates} onChange={(e) => setFrom(e.target.value)} />
        <Input label="To" type="date" value={to} disabled={!useDates} onChange={(e) => setTo(e.target.value)} />
        <Select
          label="Team"
          value={groupId ?? ''}
          onChange={(e) => setGroupId(e.target.value ? Number(e.target.value) : undefined)}
          className="min-w-52"
        >
          <option value="">All teams</option>
          {groups.data?.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </Select>
      </Card>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <Stat label="Incidents" value={h.incidents.toLocaleString()} delta={delta('incidents')} deltaNote={note} spark={spark('incidents')} />
        <Stat label="Open now" value={h.open.toLocaleString()} hint="Status New, In Progress or On Hold" />
        <Stat label="SLA breaches" value={h.sla_breaches.toLocaleString()} delta={delta('sla_breaches')} deltaNote={note} lowerIsBetter spark={spark('sla_breaches')} />
        <Stat label="SLA breach rate" value={`${h.sla_breach_rate_pct ?? 0}%`} delta={delta('sla_breach_rate_pct')} deltaNote={note && `pts ${note}`} lowerIsBetter spark={spark('sla_breach_rate_pct')} />
        <Stat label="MTTR" value={`${h.mttr_hours ?? 0} h`} delta={delta('mttr_hours')} deltaNote={note && `h ${note}`} lowerIsBetter spark={spark('mttr_hours')} />
        <Stat label="Reopen rate" value={`${h.reopen_rate_pct ?? 0}%`} delta={delta('reopen_rate_pct')} deltaNote={note && `pts ${note}`} lowerIsBetter spark={spark('reopen_rate_pct')} />
      </div>
      <p className="mb-5 mt-2 text-xs text-slate-500">
        As of {data.as_of}. Sparklines show the monthly trend{note && `; arrows compare ${note}, green = better`}. Breach = resolution time over the
        priority's SLA target (wall-clock).
      </p>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardTitle
            hint={
              <span className="flex gap-1">
                {(['sla_breaches', 'sla_breach_rate_pct'] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setMeasure(m)}
                    className={`rounded-md px-2 py-1 text-xs font-medium ${measure === m ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600'}`}
                  >
                    {m === 'sla_breaches' ? 'Count' : 'Rate %'}
                  </button>
                ))}
              </span>
            }
          >
            SLA breaches by team
          </CardTitle>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={[...data.by_team].sort((a, b) => b[measure] - a[measure])} layout="vertical" margin={{ left: 20, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
              <XAxis type="number" />
              <YAxis type="category" dataKey="team" width={140} />
              <Tooltip />
              <Bar isAnimationActive={false}
                dataKey={measure}
                name={measure === 'sla_breaches' ? 'Breaches' : 'Breach rate %'}
                fill="#4F46E5"
                radius={[0, 6, 6, 0]}
                cursor="pointer"
                onClick={(entry) => openTeam(String((entry as { team?: string }).team ?? (entry as { payload?: { team: string } }).payload?.team))}
              />
            </BarChart>
          </ResponsiveContainer>
          <p className="text-xs text-slate-500">Click a bar to open that team's incidents. Count and rate can rank teams differently.</p>
        </Card>

        <Card className="xl:col-span-2">
          <CardTitle>Team scorecard</CardTitle>
          <table className="w-full text-sm [&_td]:px-2 [&_th]:px-2 [&_th]:whitespace-nowrap">
            <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-1.5">Team</th>
                <th>Open</th>
                <th>Breaches</th>
                <th className="w-32">Breach %</th>
                <th>MTTR h</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.by_team.map((t) => (
                <tr key={t.team} onClick={() => openTeam(t.team)} className="cursor-pointer hover:bg-brand-50">
                  <td className="whitespace-nowrap py-2 font-medium text-slate-800">{t.team}</td>
                  <td>{t.open}</td>
                  <td>{t.sla_breaches}</td>
                  <td>
                    <div className="flex items-center gap-2">
                      <div className="h-2 w-12 shrink-0 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${Math.min(100, (t.sla_breach_rate_pct / 40) * 100)}%`, background: t.sla_breach_rate_pct > 20 ? '#DC2626' : '#4F46E5' }}
                        />
                      </div>
                      <span className="w-10 text-right text-xs">{t.sla_breach_rate_pct}%</span>
                    </div>
                  </td>
                  <td>{t.mttr_hours}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <Card className="mt-5">
        <CardTitle>Monthly trend (by month opened)</CardTitle>
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={months} margin={{ right: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="month" />
            <YAxis yAxisId="left" />
            <YAxis yAxisId="right" orientation="right" unit="%" />
            <Tooltip />
            <Legend />
            <Bar isAnimationActive={false} yAxisId="left" dataKey="incidents" name="Incidents" fill="#C7D2FE" radius={[6, 6, 0, 0]} />
            <Line isAnimationActive={false} yAxisId="right" dataKey="sla_breach_rate_pct" name="Breach rate %" stroke="#DC2626" strokeWidth={2.5} dot={{ r: 4 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </Card>

      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card>
          <CardTitle>By priority</CardTitle>
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={data.by_priority}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="priority" />
              <YAxis />
              <Tooltip />
              <Bar isAnimationActive={false} dataKey="incidents" name="Incidents" radius={[6, 6, 0, 0]}>
                {data.by_priority.map((p) => (
                  <ChartCell key={p.priority} fill={PRIORITY_COLORS[Number(p.priority.slice(1))]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card>
          <CardTitle>By status</CardTitle>
          <ResponsiveContainer width="100%" height={230}>
            <PieChart>
              <Pie isAnimationActive={false} data={data.by_status} dataKey="incidents" nameKey="status" innerRadius={50} outerRadius={85} paddingAngle={2}>
                {data.by_status.map((s) => (
                  <ChartCell key={s.status} fill={STATUS_COLORS[s.status] ?? '#94A3B8'} />
                ))}
              </Pie>
              <Tooltip />
              <Legend iconSize={10} wrapperStyle={{ fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
        </Card>
        <Card>
          <CardTitle>Upcoming changes by risk</CardTitle>
          {data.upcoming_changes_by_risk.length === 0 ? (
            <p className="text-sm text-slate-500">No open changes planned after the as-of date.</p>
          ) : (
            <ResponsiveContainer width="100%" height={230}>
              <BarChart data={data.upcoming_changes_by_risk}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="risk" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar isAnimationActive={false} dataKey="changes" name="Changes" radius={[6, 6, 0, 0]}>
                  {data.upcoming_changes_by_risk.map((c) => (
                    <ChartCell key={c.risk} fill={RISK_COLORS[c.risk]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>
    </>
  )
}
