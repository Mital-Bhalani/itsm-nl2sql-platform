import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Cell } from '@/lib/api'
import { TOOLTIP } from '@/components/ui'

/** Pick a chart for a query result: one label column plus a number. Returns null when unsuitable. */
export function chartSpec(columns: string[], rows: Cell[][]) {
  if (rows.length < 2 || rows.length > 60) return null
  const isId = (c: string) => c.toLowerCase() === 'id' || c.toLowerCase().endsWith('_id')
  const numeric = columns.filter((c, i) => !isId(c) && rows.every((r) => r[i] === null || typeof r[i] === 'number'))
  let labels = columns.filter((c) => !numeric.includes(c) && !isId(c))
  let values = numeric
  let data = rows.map((r) => Object.fromEntries(columns.map((c, i) => [c, r[i]])))
  if (!labels.length && numeric.includes('priority')) {
    labels = ['priority']
    values = numeric.filter((c) => c !== 'priority')
    data = data.map((d) => ({ ...d, priority: `P${d.priority}` }))
  }
  if (!labels.length || !values.length) return null
  const label = labels[0]
  const measure = values[0]
  const time = ['month', 'week', 'day', 'date'].includes(label.toLowerCase()) || data.every((d) => /^\d{4}-\d{2}/.test(String(d[label])))
  return { label, measure, time, data }
}

export default function AutoChart({ spec }: { spec: NonNullable<ReturnType<typeof chartSpec>> }) {
  const { label, measure, time, data } = spec
  if (time) {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
          <XAxis dataKey={label} />
          <YAxis />
          <Tooltip {...TOOLTIP} />
          <Line isAnimationActive={false} type="monotone" dataKey={measure} stroke="#4F46E5" strokeWidth={2.5} dot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    )
  }
  const sorted = [...data].sort((a, b) => Number(b[measure] ?? 0) - Number(a[measure] ?? 0))
  return (
    <ResponsiveContainer width="100%" height={Math.max(180, sorted.length * 34)}>
      <BarChart data={sorted} layout="vertical" margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" horizontal={false} />
        <XAxis type="number" />
        <YAxis type="category" dataKey={label} width={150} />
        <Tooltip {...TOOLTIP} />
        <Bar isAnimationActive={false} dataKey={measure} fill="#4F46E5" radius={[0, 6, 6, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}
