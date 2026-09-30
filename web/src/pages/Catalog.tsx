import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Badge, Card, DataTable, ErrorBox, Input, PageHeader, Select, Spinner, cn } from '@/components/ui'
import { api } from '@/lib/api'
import { useSettings } from '@/lib/settings'

type Glossary = {
  term: string
  kind: string
  synonyms: string | null
  definition: string
  sql_hint: string | null
  metric_name: string | null
  is_answerable: number
  is_ambiguous: number
  ambiguity_note: string | null
}
type Metric = {
  metric_name: string
  description: string
  unit: string
  base_table: string
  base_alias: string
  sql_expression: string
  required_joins: string | null
  filters: string | null
  notes: string | null
}

const TABS = ['glossary', 'metrics', 'columns', 'tables', 'joins'] as const

export default function CatalogPage() {
  const { dataset } = useSettings()
  const [tab, setTab] = useState<(typeof TABS)[number]>('glossary')
  const [text, setText] = useState('')
  const [only, setOnly] = useState('all')
  const [table, setTable] = useState('incidents')
  const section = useQuery({ queryKey: ['catalog', dataset, tab], queryFn: () => api.catalog<Record<string, unknown>>(tab, dataset) })

  return (
    <>
      <PageHeader
        title="Semantic catalog"
        subtitle="The business meaning the model is given: glossary, metrics, columns and joins. Ambiguous and not-answerable items are flagged."
      />
      <div className="mb-4 flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn('-mb-px border-b-2 px-4 py-2 text-sm font-medium capitalize', tab === t ? 'border-brand-600 text-brand-700' : 'border-transparent text-slate-500')}
          >
            {t}
          </button>
        ))}
      </div>
      {section.isLoading && <Spinner />}
      <ErrorBox error={section.error} />

      {section.data && tab === 'glossary' && (() => {
        const needle = text.toLowerCase()
        const rows = (section.data as unknown as Glossary[]).filter(
          (g) =>
            (!needle || g.term.toLowerCase().includes(needle) || (g.synonyms ?? '').toLowerCase().includes(needle)) &&
            (only === 'all' || (only === 'ambiguous' ? g.is_ambiguous : !g.is_answerable)),
        )
        return (
          <>
            <div className="mb-4 flex flex-wrap items-end gap-3">
              <Input label="Search terms and synonyms" placeholder="e.g. sev1, breach, last month" value={text} onChange={(e) => setText(e.target.value)} className="w-80" />
              <Select label="Show" value={only} onChange={(e) => setOnly(e.target.value)}>
                <option value="all">All</option>
                <option value="ambiguous">Ambiguous</option>
                <option value="unanswerable">Not answerable</option>
              </Select>
              <span className="pb-2 text-sm text-slate-500">
                {rows.length} of {section.data.length} terms
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {rows.map((g) => (
                <Card key={g.term} className="p-4">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-slate-900">{g.term}</span>
                    <Badge color="#64748B">{g.kind}</Badge>
                    {!g.is_answerable && <Badge color="#DC2626">not answerable</Badge>}
                    {!!g.is_ambiguous && <Badge color="#CA8A04">ambiguous</Badge>}
                  </div>
                  {g.synonyms && <p className="text-xs text-slate-500">Also: {g.synonyms}</p>}
                  <p className="mt-1 text-sm text-slate-700">{g.definition}</p>
                  {g.sql_hint && <pre className="mt-2 overflow-auto rounded-lg bg-slate-50 p-2 font-mono text-xs text-slate-700">{g.sql_hint}</pre>}
                  {g.ambiguity_note && <p className="mt-1 text-xs text-amber-700">{g.ambiguity_note}</p>}
                </Card>
              ))}
            </div>
          </>
        )
      })()}

      {section.data && tab === 'metrics' && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {(section.data as unknown as Metric[]).map((m) => (
            <Card key={m.metric_name}>
              <div className="mb-1 flex items-center gap-2">
                <span className="font-semibold">{m.metric_name}</span>
                <Badge color="#64748B">{m.unit}</Badge>
              </div>
              <p className="text-sm text-slate-600">{m.description}</p>
              <pre className="mt-3 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-xs text-slate-100">
                {`SELECT ${m.sql_expression}\nFROM ${m.base_table} ${m.base_alias}${m.required_joins ? `\n${m.required_joins}` : ''}${m.filters ? `\nWHERE ${m.filters}` : ''}`}
              </pre>
              {m.notes && <p className="mt-2 text-xs text-slate-500">{m.notes}</p>}
            </Card>
          ))}
        </div>
      )}

      {section.data && tab === 'columns' && (
        <>
          <Select label="Table" value={table} onChange={(e) => setTable(e.target.value)} className="mb-4 w-60">
            {[...new Set(section.data.map((c) => String(c.table_name)))].sort().map((t) => (
              <option key={t}>{t}</option>
            ))}
          </Select>
          <DataTable
            columns={['column_name', 'data_type', 'description', 'allowed_values', 'references_to', 'example_value', 'synonyms', 'is_pii', 'is_ambiguous']}
            rows={section.data.filter((c) => c.table_name === table)}
          />
        </>
      )}

      {section.data && (tab === 'tables' || tab === 'joins') && section.data.length > 0 && (
        <DataTable columns={Object.keys(section.data[0])} rows={section.data} />
      )}
    </>
  )
}
