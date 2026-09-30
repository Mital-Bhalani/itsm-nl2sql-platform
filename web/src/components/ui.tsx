// Small shadcn-style building blocks (Tailwind only, no runtime dependency).
import { clsx, type ClassValue } from 'clsx'
import { AlertTriangle, Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode, SelectHTMLAttributes, InputHTMLAttributes } from 'react'
import { Area, AreaChart, ResponsiveContainer } from 'recharts'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('rounded-2xl border border-slate-200 bg-white p-5 shadow-sm', className)}>{children}</div>
}

export function CardTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h3 className="text-base font-semibold text-slate-900">{children}</h3>
      {hint && <span className="text-xs text-slate-500">{hint}</span>}
    </div>
  )
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle: string; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4 rounded-2xl bg-gradient-to-r from-brand-600 to-violet-600 px-7 py-6 text-white shadow-sm">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">{title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-brand-100">{subtitle}</p>
      </div>
      {children}
    </div>
  )
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' }

export function Button({ variant = 'secondary', className, ...props }: ButtonProps) {
  return (
    <button
      {...props}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50',
        variant === 'primary' && 'bg-brand-600 text-white shadow-sm hover:bg-brand-700',
        variant === 'secondary' && 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50',
        variant === 'ghost' && 'text-slate-600 hover:bg-slate-100',
        className,
      )}
    />
  )
}

export function Select({ label, className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  return (
    <label className={cn('flex flex-col gap-1 text-xs font-medium text-slate-500', className)}>
      {label}
      <select
        {...props}
        className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
      >
        {children}
      </select>
    </label>
  )
}

export function Input({ label, className, ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  return (
    <label className={cn('flex flex-col gap-1 text-xs font-medium text-slate-500', className)}>
      {label}
      <input
        {...props}
        className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
      />
    </label>
  )
}

export function Badge({ children, color = '#4F46E5' }: { children: ReactNode; color?: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold"
      style={{ color, background: `${color}14`, borderColor: `${color}55` }}
    >
      {children}
    </span>
  )
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-slate-500">
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  )
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>{error instanceof Error ? error.message : String(error)}</span>
    </div>
  )
}

export function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warn' | 'ok' }) {
  const styles = {
    info: 'border-sky-200 bg-sky-50 text-sky-800',
    warn: 'border-amber-200 bg-amber-50 text-amber-800',
    ok: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  }[tone]
  return <div className={cn('rounded-xl border px-4 py-3 text-sm', styles)}>{children}</div>
}

/** KPI tile with an optional sparkline and a delta where lower (or higher) is better. */
export function Stat({
  label,
  value,
  delta,
  deltaNote,
  lowerIsBetter = false,
  spark,
  hint,
}: {
  label: string
  value: ReactNode
  delta?: number | null
  deltaNote?: string
  lowerIsBetter?: boolean
  spark?: number[]
  hint?: string
}) {
  const good = delta == null || delta === 0 ? null : lowerIsBetter ? delta < 0 : delta > 0
  return (
    <div className="flex flex-col rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" title={hint}>
      <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
      <span className="mt-1 text-2xl font-bold text-slate-900">{value}</span>
      {delta != null && (
        <span
          className={cn(
            'mt-1 text-xs font-semibold',
            good === null ? 'text-slate-500' : good ? 'text-emerald-600' : 'text-red-600',
          )}
        >
          {delta > 0 ? '▲' : delta < 0 ? '▼' : '■'} {delta > 0 ? '+' : ''}
          {Math.round(delta * 10) / 10}
          {deltaNote && <span className="ml-1 font-normal text-slate-400">{deltaNote}</span>}
        </span>
      )}
      {spark && spark.length > 1 && (
        <div className="mt-2 h-10">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={spark.map((v, i) => ({ i, v }))}>
              <Area type="monotone" dataKey="v" stroke="#4F46E5" fill="#E0E7FF" strokeWidth={2} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

export function DataTable({
  columns,
  rows,
  onRowClick,
  maxHeight = 460,
}: {
  columns: string[]
  rows: Record<string, unknown>[]
  onRowClick?: (row: Record<string, unknown>) => void
  maxHeight?: number
}) {
  return (
    <div className="overflow-auto rounded-xl border border-slate-200" style={{ maxHeight }}>
      <table className="min-w-full text-sm">
        <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {columns.map((c) => (
              <th key={c} className="whitespace-nowrap px-3 py-2 font-semibold">
                {c.replaceAll('_', ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {rows.map((row, i) => (
            <tr
              key={i}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={cn(onRowClick && 'cursor-pointer hover:bg-brand-50')}
            >
              {columns.map((c) => (
                <td key={c} className="whitespace-nowrap px-3 py-2 text-slate-700">
                  {row[c] === null || row[c] === undefined ? <span className="text-slate-300">—</span> : String(row[c])}
                </td>
              ))}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-3 py-6 text-center text-slate-400">
                No rows
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export function toCsv(columns: string[], rows: unknown[][]) {
  const escape = (v: unknown) => {
    const text = v === null || v === undefined ? '' : String(v)
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
  }
  return [columns.map(escape).join(','), ...rows.map((r) => r.map(escape).join(','))].join('\n')
}

export function downloadCsv(filename: string, columns: string[], rows: unknown[][]) {
  const blob = new Blob([toCsv(columns, rows)], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const link = Object.assign(document.createElement('a'), { href: url, download: filename })
  link.click()
  URL.revokeObjectURL(url)
}

export const PRIORITY_COLORS: Record<number, string> = { 1: '#DC2626', 2: '#EA580C', 3: '#CA8A04', 4: '#16A34A' }
export const STATUS_COLORS: Record<string, string> = {
  New: '#2563EB',
  'In Progress': '#7C3AED',
  'On Hold': '#CA8A04',
  Resolved: '#16A34A',
  Closed: '#4B5563',
  Cancelled: '#9CA3AF',
}
export const RISK_COLORS: Record<string, string> = { High: '#DC2626', Moderate: '#EA580C', Low: '#16A34A' }
