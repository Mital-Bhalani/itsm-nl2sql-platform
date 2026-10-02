import { useQuery } from '@tanstack/react-query'
import { BookOpen, CheckCircle2, FolderSearch, LayoutDashboard, MessageSquare, ScanSearch, Star, Ticket } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useHealth } from '@/components/Layout'
import { Card, ErrorBox, Notice, PageHeader, Spinner, Stat } from '@/components/ui'
import { api } from '@/lib/api'
import { useSavedQuestions } from '@/lib/saved'
import { useSettings } from '@/lib/settings'

const PAGES = [
  { to: '/ask', label: 'Ask a question', icon: MessageSquare, text: 'Plain English in; answer, chart and SQL out. Compare two models.' },
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, text: 'SLA, MTTR and reopen trends by team, month and priority.' },
  { to: '/explorer', label: 'Data explorer', icon: FolderSearch, text: 'Browse, filter and export every table in the database.' },
  { to: '/incident', label: 'Incident detail', icon: Ticket, text: 'SLA gauge, timeline and similar incidents for one ticket.' },
  { to: '/catalog', label: 'Semantic catalog', icon: BookOpen, text: 'The glossary, metrics and joins the model is given.' },
  { to: '/evals', label: 'Evals', icon: CheckCircle2, text: 'Score the agent on the golden set, per model.' },
  { to: '/data-check', label: 'Data check', icon: ScanSearch, text: 'UI numbers vs the database, plus a read-only SQL console.' },
]

export default function HomePage() {
  const { dataset } = useSettings()
  const health = useHealth().data!
  const overview = useQuery({ queryKey: ['overview', dataset], queryFn: () => api.overview(dataset) })
  const { saved } = useSavedQuestions()

  return (
    <>
      <PageHeader
        title="ITSM Insights"
        subtitle="Ask questions about incidents, SLAs and changes in plain English. Every answer shows the SQL it ran, read-only."
      />
      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Stat label="Service status" value={health.status.toUpperCase()} />
        <Stat
          label="Model providers ready"
          value={`${health.providers.filter((p) => p.configured).length} / ${health.providers.length}`}
        />
        <Stat label="Data as of" value={health.as_of} />
      </div>
      {!health.llm_ready && (
        <div className="mb-6">
          <Notice tone="warn">
            No language-model API key is configured, so Ask and live evals will not work. Dashboards, the explorer and
            the catalog still do.
          </Notice>
        </div>
      )}

      <h2 className="mb-3 text-lg font-semibold">Dataset: {dataset}</h2>
      {overview.isLoading && <Spinner />}
      <ErrorBox error={overview.error} />
      {overview.data && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
            {Object.entries(overview.data.row_counts).map(([table, n]) => (
              <Stat key={table} label={table.replaceAll('_', ' ')} value={n.toLocaleString()} />
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">
            Incidents opened {overview.data.incidents_from.slice(0, 10)} to {overview.data.incidents_to.slice(0, 10)} ·
            catalog: {overview.data.catalog_counts.glossary} glossary terms, {overview.data.catalog_counts.metrics}{' '}
            metrics, {overview.data.catalog_counts.columns} columns
          </p>
        </>
      )}

      {saved.length > 0 && (
        <Card className="mt-8" data-testid="home-saved">
          <h3 className="mb-2 flex items-center gap-1.5 font-semibold">
            <Star className="size-4 fill-amber-400 text-amber-400" /> Your saved questions
          </h3>
          <div className="flex flex-wrap gap-2">
            {saved.map((q) => (
              <Link
                key={q}
                to={`/ask?q=${encodeURIComponent(q)}`}
                className="rounded-full border border-brand-edge bg-brand-soft px-3 py-1.5 text-sm text-brand-text hover:bg-brand-soft-2"
              >
                {q}
              </Link>
            ))}
          </div>
        </Card>
      )}

      <h2 className="mb-3 mt-8 text-lg font-semibold">Where to go</h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {PAGES.map(({ to, label, icon: Icon, text }) => (
          <Link key={to} to={to}>
            <Card className="h-full transition hover:-translate-y-0.5 hover:border-brand-edge hover:shadow-md">
              <div className="mb-2 flex items-center gap-2 font-semibold text-ink">
                <span className="rounded-lg bg-brand-soft p-2 text-brand-text">
                  <Icon className="size-4" />
                </span>
                {label}
              </div>
              <p className="text-sm text-muted">{text}</p>
            </Card>
          </Link>
        ))}
      </div>

      <Card className="mt-8">
        <h3 className="mb-2 font-semibold">Safety and data handling</h3>
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
          <li>The database is opened read-only; only one SELECT can run, with a row limit and a 5-second timeout.</li>
          <li>Personal data (user names) is masked in the explorer and blocked in generated SQL.</li>
          <li>People appear as user id and role only. Questions about data that does not exist (categories, contact details, satisfaction scores…) are refused instead of guessed.</li>
          <li>Every question is recorded in the API's audit log with the SQL and model used.</li>
        </ul>
      </Card>
    </>
  )
}
