import { Ban, Download, Info, Send, Star, ThumbsDown, ThumbsUp, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import AutoChart, { chartSpec } from '@/components/AutoChart'
import { useModel } from '@/components/Layout'
import { Button, Card, DataTable, ErrorBox, Notice, PageHeader, Spinner, cn, downloadCsv } from '@/components/ui'
import { api, type AskResult, type AskTurn } from '@/lib/api'
import { useSavedQuestions } from '@/lib/saved'
import { useSettings } from '@/lib/settings'

const EXAMPLES = [
  'Which assignment groups breached SLA most last month?',
  'What is the SLA breach rate by team last month?',
  'How many P1 incidents are open?',
  'What is the MTTR for each priority?',
  'How many incidents were opened each month?',
  'Which high-risk changes are scheduled next week?',
]

type Entry = { question: string; results: (AskResult | { error: string; provider?: string; model?: string })[]; loading: boolean }

function isAnswer(r: Entry['results'][number]): r is AskResult {
  return 'request_id' in r
}

function Result({ result, question, latest, onAsk }: {
  result: Entry['results'][number]
  question: string
  latest: boolean
  onAsk: (q: string) => void
}) {
  const [tab, setTab] = useState<'chart' | 'table' | 'sql'>('chart')
  const [rated, setRated] = useState<'up' | 'down' | null>(null)
  if (!isAnswer(result)) return <ErrorBox error={result.error} />
  if (result.refusal) {
    return (
      <div className="flex items-start gap-2 rounded-xl border border-tone-warn bg-tone-warn px-4 py-3 text-sm text-tone-warn">
        <Ban className="mt-0.5 size-4 shrink-0" /> {result.refusal}
      </div>
    )
  }
  const spec = result.columns.length ? chartSpec(result.columns, result.rows) : null
  const active = tab === 'chart' && !spec ? 'table' : tab
  const rate = async (rating: 'up' | 'down') => {
    setRated(rating)
    try {
      await api.feedback({ request_id: result.request_id, rating, question })
    } catch {
      setRated(null)
    }
  }
  return (
    <div className="flex flex-col gap-3">
      {result.answer && <p className="text-lg font-semibold leading-snug text-ink">{result.answer}</p>}
      {result.error && <ErrorBox error={result.error} />}
      {result.assumption && (
        <div className="flex items-start gap-2 rounded-xl border border-tone-info bg-tone-info px-3 py-2 text-sm text-tone-info">
          <Info className="mt-0.5 size-4 shrink-0" /> Assumption: {result.assumption}
        </div>
      )}
      {result.sql && (
        <div>
          <div className="mb-2 flex gap-1 border-b border-line">
            {(['chart', 'table', 'sql'] as const)
              .filter((t) => t !== 'chart' || spec)
              .map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={cn(
                    '-mb-px border-b-2 px-3 py-1.5 text-sm font-medium capitalize',
                    active === t ? 'border-brand-600 text-brand-text' : 'border-transparent text-muted hover:text-ink-2',
                  )}
                >
                  {t === 'sql' ? 'SQL' : t}
                </button>
              ))}
          </div>
          {active === 'chart' && spec && <AutoChart spec={spec} />}
          {active === 'table' && (
            <>
              <DataTable
                columns={result.columns}
                rows={result.rows.map((r) => Object.fromEntries(result.columns.map((c, i) => [c, r[i]])))}
                maxHeight={320}
              />
              <div className="mt-2 flex items-center justify-between text-xs text-muted">
                <span>
                  {result.row_count} rows{result.truncated ? ' (capped at 1,000)' : ''}
                </span>
                <Button variant="ghost" onClick={() => downloadCsv('answer.csv', result.columns, result.rows)}>
                  <Download className="size-3.5" /> CSV
                </Button>
              </div>
            </>
          )}
          {active === 'sql' && (
            <>
              {result.repaired && <p className="mb-1 text-xs text-muted">The first SQL failed; this is the corrected version.</p>}
              <pre className="overflow-auto rounded-xl bg-code p-4 font-mono text-xs leading-relaxed text-code-ink">{result.sql}</pre>
            </>
          )}
        </div>
      )}
      <div className="flex items-center justify-between text-xs text-muted">
        <span>
          {result.provider} / {result.model} · {((result.timings.total_ms ?? 0) / 1000).toFixed(1)} s
          {result.tokens_in != null && ` · ${result.tokens_in.toLocaleString()} in / ${(result.tokens_out ?? 0).toLocaleString()} out tokens`}
        </span>
        <span className="flex items-center gap-1">
          {rated && <span className="mr-1">Thanks!</span>}
          <button onClick={() => rate('up')} className={cn('rounded p-1 hover:bg-surface-3', rated === 'up' && 'text-tone-ok')} title="Helpful">
            <ThumbsUp className="size-4" />
          </button>
          <button onClick={() => rate('down')} className={cn('rounded p-1 hover:bg-surface-3', rated === 'down' && 'text-tone-bad')} title="Not helpful">
            <ThumbsDown className="size-4" />
          </button>
        </span>
      </div>
      {latest && result.followups.length > 0 && (
        <div>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Ask next</div>
          <div className="flex flex-wrap gap-2">
            {result.followups.map((f) => (
              <button
                key={f}
                onClick={() => onAsk(f)}
                className="rounded-full border border-brand-edge bg-brand-soft px-3 py-1.5 text-left text-sm text-brand-text hover:bg-brand-soft-2"
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function AskPage() {
  const { dataset } = useSettings()
  const { provider, model, providers } = useModel()
  const [history, setHistory] = useState<Entry[]>([])
  const savedQuestions = useSavedQuestions()
  const [text, setText] = useState('')
  const [compare, setCompare] = useState(false)
  const others = providers.filter((p) => p.name !== provider?.name)
  const [second, setSecond] = useState('')
  const bottom = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // Braces matter: newer browsers return a Promise here, which React would treat as a cleanup.
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history])
  const [params, setParams] = useSearchParams()
  const asked = useRef(false)

  const ask = async (question: string) => {
    if (!question.trim() || !provider) return
    const targets = [{ provider: provider.name, model }]
    const secondSpec = others.find((p) => p.name === second) ?? others[0]
    if (compare && secondSpec) targets.push({ provider: secondSpec.name, model: secondSpec.default_model })
    const index = history.length
    // Earlier exchanges of this thread (last three that produced SQL) give follow-ups their context.
    const thread: AskTurn[] = history
      .map((entry) => entry.results.find(isAnswer))
      .filter((r): r is AskResult => !!r && !!r.sql)
      .map((r) => ({ question: r.question, sql: r.sql }))
      .slice(-3)
    setHistory((h) => [...h, { question, results: [], loading: true }])
    setText('')
    const results = await Promise.all(
      targets.map((t) =>
        api.ask({ question, provider: t.provider, model: t.model, dataset, history: thread }).catch((e: Error) => ({
          error: e.message,
          provider: t.provider,
          model: t.model,
        })),
      ),
    )
    setHistory((h) => h.map((entry, i) => (i === index ? { ...entry, results, loading: false } : entry)))
  }

  // A link such as #/ask?q=How%20many%20P1%20incidents%20are%20open%3F asks straight away.
  useEffect(() => {
    const q = params.get('q')
    if (q && provider && !asked.current) {
      asked.current = true
      setParams({}, { replace: true })
      ask(q)
    }
  })

  return (
    <>
      <PageHeader title="Ask a question" subtitle="Plain English in, a checked answer out. The SQL behind every answer is one click away.">
        <div className="flex items-center gap-3 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} className="size-4 accent-white" />
            Compare two models
          </label>
          {compare && (
            <select value={second} onChange={(e) => setSecond(e.target.value)} className="rounded-lg bg-white/15 px-2 py-1 text-white">
              {others.map((p) => (
                <option key={p.name} value={p.name} className="text-ink">
                  {p.label}
                  {p.configured ? '' : ' (no key)'}
                </option>
              ))}
            </select>
          )}
          {history.length > 0 && (
            <Button variant="ghost" className="text-white hover:bg-white/10" onClick={() => setHistory([])}>
              <Trash2 className="size-4" /> Clear
            </Button>
          )}
        </div>
      </PageHeader>

      {!providers.some((p) => p.configured) && <Notice tone="warn">No model API key is configured, so questions cannot be answered yet.</Notice>}

      <div className="flex flex-col gap-5 pb-28">
        {savedQuestions.saved.length > 0 && (
          <div data-testid="saved-questions">
            <p className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink-2">
              <Star className="size-4 fill-amber-400 text-amber-400" /> Saved
            </p>
            <div className="flex flex-wrap gap-2">
              {savedQuestions.saved.map((q) => (
                <span key={q} className="inline-flex items-center gap-1 rounded-full border border-line bg-surface pl-3 pr-1 text-sm shadow-sm">
                  <button onClick={() => ask(q)} className="py-1.5 text-left text-ink-2 hover:text-brand-text">
                    {q}
                  </button>
                  <button
                    onClick={() => savedQuestions.remove(q)}
                    aria-label={`Remove saved question: ${q}`}
                    className="rounded-full p-1 text-faint hover:bg-surface-3 hover:text-ink"
                  >
                    <X className="size-3.5" />
                  </button>
                </span>
              ))}
            </div>
          </div>
        )}
        {history.length === 0 && (
          <div>
            <p className="mb-3 text-sm font-medium text-ink-2">Try one of these:</p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {EXAMPLES.map((e) => (
                <button key={e} onClick={() => ask(e)} className="rounded-xl border border-line bg-surface px-4 py-3 text-left text-sm shadow-sm hover:border-brand-edge hover:bg-brand-soft">
                  {e}
                </button>
              ))}
            </div>
          </div>
        )}
        {history.map((entry, i) => (
          <div key={i} className="flex flex-col gap-3">
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => savedQuestions.toggle(entry.question)}
                aria-label={savedQuestions.isSaved(entry.question) ? 'Remove from saved questions' : 'Save this question'}
                aria-pressed={savedQuestions.isSaved(entry.question)}
                title={savedQuestions.isSaved(entry.question) ? 'Saved' : 'Save question'}
                className="rounded-full p-1.5 text-faint hover:bg-surface-3 hover:text-amber-500"
              >
                <Star className={cn('size-4', savedQuestions.isSaved(entry.question) && 'fill-amber-400 text-amber-400')} />
              </button>
              <div className="rounded-2xl rounded-br-sm bg-brand-600 px-4 py-2.5 text-sm text-white shadow-sm">{entry.question}</div>
            </div>
            <Card>
              {entry.loading ? (
                <Spinner label="Writing SQL, running it and reading the result…" />
              ) : entry.results.length === 1 ? (
                <Result result={entry.results[0]} question={entry.question} latest={i === history.length - 1} onAsk={ask} />
              ) : (
                <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
                  {entry.results.map((r, n) => (
                    <div key={n}>
                      <div className="mb-2 text-xs font-bold uppercase tracking-wide text-brand-text">
                        {r.provider} / {r.model}
                      </div>
                      <Result result={r} question={entry.question} latest={i === history.length - 1 && n === 0} onAsk={ask} />
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          ask(text)
        }}
        className="fixed bottom-4 left-4 right-4 flex gap-2 rounded-2xl border border-line bg-surface p-2 shadow-lg sm:left-6 sm:right-6 lg:bottom-5 lg:left-72 lg:right-8"
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask about incidents, SLAs, teams or changes…"
          className="min-w-0 flex-1 rounded-xl bg-transparent px-3 py-2 text-sm text-ink outline-none placeholder:text-faint"
        />
        <Button variant="primary" type="submit" disabled={!text.trim()}>
          <Send className="size-4" /> Ask
        </Button>
      </form>
    </>
  )
}
