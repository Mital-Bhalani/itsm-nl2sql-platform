import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Download } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Card, DataTable, ErrorBox, Input, PageHeader, Select, Spinner, cn, downloadCsv } from '@/components/ui'
import { api } from '@/lib/api'
import { useSettings } from '@/lib/settings'

const ORDER = ['incidents', 'changes', 'assignment_groups', 'users', 'sla_targets']

export default function ExplorerPage() {
  const { dataset } = useSettings()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const table = params.get('table') ?? 'incidents'
  const team = params.get('team') ?? ''

  const tables = useQuery({ queryKey: ['tables', dataset], queryFn: () => api.tables(dataset) })
  const groups = useQuery({ queryKey: ['groups', dataset], queryFn: () => api.groups(dataset) })
  const spec = tables.data?.find((t) => t.table_name === table)

  const [filters, setFilters] = useState<Record<string, string>>({})
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('')
  const [desc, setDesc] = useState(true)
  const [size, setSize] = useState(50)
  const [page, setPage] = useState(1)

  // A team passed in the URL (from the dashboard) becomes the team filter.
  useEffect(() => {
    const id = groups.data?.find((g) => g.name === team)?.id
    setFilters(id ? { assignment_group_id: String(id) } : {})
    setSearch('')
    setSort('')
    setDesc(table === 'incidents' || table === 'changes')
    setPage(1)
  }, [table, team, groups.data])

  const query = {
    dataset,
    search: search || undefined,
    sort: sort || undefined,
    desc,
    page,
    size,
    ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v).map(([k, v]) => [`f_${k}`, v])),
  }
  const data = useQuery({
    queryKey: ['browse', table, query],
    queryFn: () => api.browse(table, query),
    placeholderData: keepPreviousData,
    enabled: !!spec,
  })

  const setFilter = (column: string, value: string) => {
    setFilters((f) => ({ ...f, [column]: value }))
    setPage(1)
    if (column === 'assignment_group_id' && team) setParams({ table })
  }

  if (tables.isLoading) return <Spinner />
  if (tables.error) return <ErrorBox error={tables.error} />

  const filterable = spec?.columns.filter((c) => c.allowed_values || ['priority', 'assignment_group_id'].includes(c.column_name)) ?? []

  return (
    <>
      <PageHeader title="Data explorer" subtitle="Browse every table in the database: filter, search, sort, page and export. User names are masked." />

      <div className="mb-4 flex flex-wrap gap-2">
        {ORDER.filter((n) => tables.data?.some((t) => t.table_name === n)).map((n) => {
          const t = tables.data!.find((x) => x.table_name === n)!
          return (
            <button
              key={n}
              onClick={() => setParams({ table: n })}
              className={cn(
                'rounded-full border px-4 py-1.5 text-sm font-medium',
                n === table ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50',
              )}
            >
              {n.replaceAll('_', ' ')} <span className="opacity-70">({t.rows.toLocaleString()})</span>
            </button>
          )
        })}
      </div>
      {spec && <p className="mb-4 text-sm text-slate-500">{spec.description} Grain: {spec.grain}</p>}

      <Card className="mb-4 flex flex-wrap items-end gap-3">
        {filterable.map((c) => (
          <Select
            key={c.column_name}
            label={c.column_name === 'assignment_group_id' ? 'Team' : c.column_name.replaceAll('_', ' ')}
            value={filters[c.column_name] ?? ''}
            onChange={(e) => setFilter(c.column_name, e.target.value)}
          >
            <option value="">Any</option>
            {c.column_name === 'assignment_group_id'
              ? groups.data?.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))
              : c.column_name === 'priority'
                ? [1, 2, 3, 4].map((p) => (
                    <option key={p} value={p}>
                      P{p}
                    </option>
                  ))
                : c.allowed_values!.split(',').map((v) => (
                    <option key={v.trim()} value={v.trim()}>
                      {v.trim()}
                    </option>
                  ))}
          </Select>
        ))}
        <Input label="Search text" placeholder="e.g. printer" value={search} onChange={(e) => (setSearch(e.target.value), setPage(1))} />
        <Select label="Sort by" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="">(table order)</option>
          {spec?.columns
            .filter((c) => !c.is_pii)
            .map((c) => (
              <option key={c.column_name} value={c.column_name}>
                {c.column_name}
              </option>
            ))}
        </Select>
        <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
          <input type="checkbox" checked={desc} onChange={(e) => setDesc(e.target.checked)} className="size-4 accent-brand-600" /> Descending
        </label>
        <Select label="Rows" value={size} onChange={(e) => (setSize(Number(e.target.value)), setPage(1))}>
          {[25, 50, 100, 200].map((n) => (
            <option key={n}>{n}</option>
          ))}
        </Select>
      </Card>

      <ErrorBox error={data.error} />
      {data.data && (
        <>
          <DataTable
            columns={data.data.columns}
            rows={data.data.rows}
            onRowClick={table === 'incidents' ? (row) => navigate(`/incident?id=${row.id}`) : undefined}
            maxHeight={560}
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
            <Button onClick={() => setPage((p) => p - 1)} disabled={page <= 1}>
              <ChevronLeft className="size-4" /> Previous
            </Button>
            <span>
              Page {data.data.page} of {data.data.pages} · {data.data.total.toLocaleString()} matching rows
              {table === 'incidents' && ' · click a row to open the incident'}
            </span>
            <div className="flex gap-2">
              <Button
                variant="ghost"
                onClick={() =>
                  downloadCsv(`${table}_page${page}.csv`, data.data!.columns, data.data!.rows.map((r) => data.data!.columns.map((c) => r[c])))
                }
              >
                <Download className="size-4" /> CSV
              </Button>
              <Button onClick={() => setPage((p) => p + 1)} disabled={page >= data.data.pages}>
                Next <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </>
      )}
    </>
  )
}
