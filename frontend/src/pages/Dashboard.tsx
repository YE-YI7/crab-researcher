/**
 * Dashboard — Agent 控制中心
 * 
 * 集成：持久化研究扫描、机会卡片、目标追踪、通知、审批队列与周报
 * 风格：与 Surface 一致的暖白卡片风格
 */

import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import type { CreatureState } from '../components/creature/types'
import { api, apiBlobUrl } from '../lib/api'
import { ArrowLeftIcon, BellIcon, TargetIcon, CalendarIcon, ShieldCheckIcon, ZapIcon, SearchSparkIcon, NewsIcon, ChartBarIcon, BrainIcon, GearIcon, PinIcon, LockIcon, CircleCheckIcon, AlertTriangleIcon, RocketIcon, GlobeIcon } from '../components/ui/Icons'

interface DashboardProps {
  creature: CreatureState
  onBack: () => void
}

type Tab = 'research' | 'browser' | 'overview' | 'notifications' | 'approvals' | 'reports'

interface ScanSummary {
  id: string
  product_id: number
  scan_type: string
  status: 'queued' | 'running' | 'completed' | 'failed' | string
  progress: number
  summary: {
    source_count?: number
    competitor_count?: number
    signal_count?: number
    opportunity_count?: number
    warnings?: string[]
  }
  error?: string | null
  created_at: string
  completed_at?: string | null
}

interface ScanSource {
  id: number
  type: string
  platform?: string | null
  title: string
  url: string
  excerpt: string
  relevance_score: number
}

interface ScanOpportunity {
  id: number
  title: string
  rationale: string
  recommended_action: string
  channel: string
  rank: number
  confidence: number
  effort: string
  expected_impact: string
  evidence_source_ids: number[]
  status: string
}

interface ScanDetail extends ScanSummary {
  product: { id: number; name: string; industry: string; category: string; keywords: string[] }
  sources: ScanSource[]
  competitors: Array<{ id: number; source_id?: number; name: string; evidence_summary: string; confidence: number }>
  market_signals: Array<{ id: number; source_id?: number; title: string; evidence_summary: string; confidence: number }>
  opportunities: ScanOpportunity[]
}

interface BrowserCapabilities {
  enabled: boolean
  provider: string
  isolation: string
  approval_required_for: string[]
  credentials_supported: boolean
}

interface BrowserJobSummary {
  id: string
  status: string
  provider: string
  goal: string
  start_url: string
  current_url?: string | null
  current_step: number
  summary: Record<string, any>
  error?: string | null
  created_at: string
}

interface BrowserJobDetail extends BrowserJobSummary {
  steps: Array<{
    id: number
    position: number
    action: string
    status: string
    requires_approval: boolean
    result: Record<string, any>
    error?: string | null
  }>
  artifacts: Array<{
    id: string
    step_id?: number | null
    kind: string
    content_type: string
    size_bytes: number
    download_url: string
  }>
}

export function Dashboard({ creature, onBack }: DashboardProps) {
  const [tab, setTab] = useState<Tab>('research')
  const [goals, setGoals] = useState<any>(null)
  const [notifications, setNotifications] = useState<any[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [pending, setPending] = useState<any[]>([])
  const [reports, setReports] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [scans, setScans] = useState<ScanSummary[]>([])
  const [activeScan, setActiveScan] = useState<ScanDetail | null>(null)
  const [scanLoading, setScanLoading] = useState(true)
  const [scanStarting, setScanStarting] = useState(false)
  const [scanError, setScanError] = useState<string | null>(null)
  const selectedScanId = useRef<string | null>(localStorage.getItem('crabres_scan_id'))

  // 加载数据
  useEffect(() => {
    const load = async () => {
      try {
        const [goalRes, notifRes, unreadRes, pendingRes, reportRes] = await Promise.all([
          api<any>('/goals').catch(() => ({ has_goal: false })),
          api<any>('/notifications?limit=30').catch(() => ({ notifications: [] })),
          api<any>('/notifications/unread').catch(() => ({ count: 0, notifications: [] })),
          api<any>('/autonomous/pending').catch(() => ({ pending: [] })),
          api<any>('/weekly-reports?limit=4').catch(() => ({ reports: [] })),
        ])
        setGoals(goalRes)
        setNotifications(notifRes.notifications || [])
        setUnreadCount(unreadRes.count || 0)
        setPending(pendingRes.pending || [])
        setReports(reportRes.reports || [])
      } catch {} finally { setLoading(false) }
    }
    load()
    const interval = setInterval(load, 30_000) // 每 30 秒刷新
    return () => clearInterval(interval)
  }, [])

  // 扫描任务使用鉴权 API 轮询；原生 EventSource 无法携带 Bearer token。
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const refresh = async () => {
      try {
        const response = await api<{ items: ScanSummary[] }>('/scans?limit=10')
        if (stopped) return
        const items = response.items || []
        setScans(items)
        const preferredId = selectedScanId.current && items.some(item => item.id === selectedScanId.current)
          ? selectedScanId.current
          : items[0]?.id
        if (preferredId) {
          const detail = await api<ScanDetail>(`/scans/${preferredId}`)
          if (!stopped) {
            setActiveScan(detail)
            selectedScanId.current = detail.id
            localStorage.setItem('crabres_scan_id', detail.id)
          }
        } else if (!stopped) {
          setActiveScan(null)
        }
        if (!stopped) setScanError(null)
        const hasActiveWork = items.some(item => item.status === 'queued' || item.status === 'running')
        if (!stopped) timer = setTimeout(refresh, hasActiveWork ? 4_000 : 30_000)
      } catch (error: any) {
        if (!stopped) {
          setScanError(error?.message || 'Could not load research scans.')
          timer = setTimeout(refresh, 30_000)
        }
      } finally {
        if (!stopped) setScanLoading(false)
      }
    }
    refresh()

    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [])

  const selectScan = async (scanId: string) => {
    selectedScanId.current = scanId
    localStorage.setItem('crabres_scan_id', scanId)
    setScanLoading(true)
    try {
      setActiveScan(await api<ScanDetail>(`/scans/${scanId}`))
      setScanError(null)
    } catch (error: any) {
      setScanError(error?.message || 'Could not load this scan.')
    } finally {
      setScanLoading(false)
    }
  }

  const startScan = async () => {
    setScanStarting(true)
    setScanError(null)
    try {
      let productId = Number(localStorage.getItem('crabres_product_id')) || 0
      if (!productId) {
        const products = await api<Array<{ id: number }>>('/products')
        productId = products[0]?.id || 0
      }
      if (!productId) throw new Error('Complete your product profile before starting a scan.')
      const market = localStorage.getItem('crabres_product_market') || 'global'
      const created = await api<ScanSummary>('/scans', {
        method: 'POST',
        headers: { 'Idempotency-Key': globalThis.crypto?.randomUUID?.() || `scan-${Date.now()}` },
        body: JSON.stringify({
          product_id: productId,
          scan_type: 'market_landscape',
          locale: market === 'domestic' ? 'zh-CN' : 'en',
          platforms: market === 'domestic'
            ? ['xiaohongshu', 'zhihu', 'bilibili']
            : ['reddit', 'hackernews', 'producthunt'],
        }),
      })
      selectedScanId.current = created.id
      localStorage.setItem('crabres_scan_id', created.id)
      setScans(previous => [created, ...previous.filter(item => item.id !== created.id)])
      setTab('research')
      await selectScan(created.id)
    } catch (error: any) {
      setScanError(error?.message || 'Could not start a new scan.')
    } finally {
      setScanStarting(false)
    }
  }

  const retryScan = async () => {
    if (!activeScan) return
    setScanStarting(true)
    setScanError(null)
    try {
      await api(`/scans/${activeScan.id}/retry`, { method: 'POST' })
      await selectScan(activeScan.id)
    } catch (error: any) {
      setScanError(error?.message || 'Could not retry this scan.')
    } finally {
      setScanStarting(false)
    }
  }

  const markRead = async (id: string) => {
    await api(`/notifications/${id}/read`, { method: 'POST' }).catch(() => {})
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n))
    setUnreadCount(prev => Math.max(0, prev - 1))
  }

  const markAllRead = async () => {
    await api('/notifications/read-all', { method: 'POST' }).catch(() => {})
    setNotifications(prev => prev.map(n => ({ ...n, read: true })))
    setUnreadCount(0)
  }

  const approveAction = async (id: string) => {
    await api(`/autonomous/${id}/approve`, { method: 'POST' }).catch(() => {})
    setPending(prev => prev.filter(a => a.id !== id))
  }

  const rejectAction = async (id: string) => {
    await api(`/autonomous/${id}/reject`, { method: 'POST' }).catch(() => {})
    setPending(prev => prev.filter(a => a.id !== id))
  }

  const tabs: { key: Tab; label: string; icon: React.ReactNode; badge?: number }[] = [
    { key: 'research', label: 'Research', icon: <SearchSparkIcon /> },
    { key: 'browser', label: 'Browser', icon: <GlobeIcon /> },
    { key: 'overview', label: 'Overview', icon: <TargetIcon /> },
    { key: 'notifications', label: 'Alerts', icon: <BellIcon />, badge: unreadCount },
    { key: 'approvals', label: 'Approve', icon: <ShieldCheckIcon />, badge: pending.length },
    { key: 'reports', label: 'Reports', icon: <CalendarIcon /> },
  ]

  return (
    <div className="min-h-screen bg-surface">
      {/* 头部 */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border bg-glass sticky top-0 z-20 max-w-3xl mx-auto">
        <button onClick={onBack} className="p-2 rounded-xl hover:bg-hover transition-colors">
          <ArrowLeftIcon />
        </button>
        <div className="flex-1">
          <p className="text-sm font-semibold text-primary">Agent Dashboard</p>
          <p className="text-[10px] text-muted flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            Auto-refreshing research and alerts
          </p>
        </div>
      </div>

      {/* Tab 导航 */}
      <div className="max-w-3xl mx-auto px-4 pt-4">
        <div className="flex gap-1 p-1 rounded-xl bg-hover">
          {tabs.map(t => (
            <button key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 text-xs font-medium rounded-lg transition-all relative ${
                tab === t.key ? 'bg-white shadow-sm text-primary dark:bg-[var(--bg-card)]' : 'text-muted hover:text-primary'
              }`}>
              {t.icon}
              <span className="hidden sm:inline">{t.label}</span>
              {t.badge && t.badge > 0 ? (
                <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-brand text-white text-[9px] font-bold flex items-center justify-center">
                  {t.badge > 9 ? '9+' : t.badge}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      </div>

      {/* 内容区 */}
      <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
        {loading ? (
          <div className="text-center py-16 text-muted text-sm">Loading dashboard...</div>
        ) : (
          <>
            {tab === 'research' && <ResearchTab scans={scans} activeScan={activeScan} loading={scanLoading} error={scanError} starting={scanStarting} onSelect={selectScan} onStart={startScan} onRetry={retryScan} />}
            {tab === 'browser' && <BrowserJobsTab />}
            {tab === 'overview' && <OverviewTab goals={goals} pending={pending} unreadCount={unreadCount} reports={reports} />}
            {tab === 'notifications' && <NotificationsTab notifications={notifications} onMarkRead={markRead} onMarkAllRead={markAllRead} />}
            {tab === 'approvals' && <ApprovalsTab pending={pending} onApprove={approveAction} onReject={rejectAction} />}
            {tab === 'reports' && <ReportsTab reports={reports} />}
          </>
        )}
      </div>
    </div>
  )
}

// === Browser Jobs Tab ===
function BrowserJobsTab() {
  const [capabilities, setCapabilities] = useState<BrowserCapabilities | null>(null)
  const [jobs, setJobs] = useState<BrowserJobSummary[]>([])
  const [activeJob, setActiveJob] = useState<BrowserJobDetail | null>(null)
  const [startUrl, setStartUrl] = useState('https://example.com')
  const [goal, setGoal] = useState('Inspect the landing page and capture the visible evidence')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(null)
  const selectedJobId = useRef<string | null>(null)

  const load = async (preferredId?: string) => {
    const [caps, list] = await Promise.all([
      api<BrowserCapabilities>('/browser-jobs/capabilities'),
      api<{ items: BrowserJobSummary[] }>('/browser-jobs?limit=10'),
    ])
    setCapabilities(caps)
    setJobs(list.items || [])
    const selectedId = preferredId || selectedJobId.current || list.items?.[0]?.id
    if (selectedId) {
      selectedJobId.current = selectedId
      setActiveJob(await api<BrowserJobDetail>(`/browser-jobs/${selectedId}`))
    }
    return (list.items || []).some(job => ['queued', 'running'].includes(job.status))
  }

  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const refresh = async () => {
      try {
        const hasActiveWork = await load()
        if (!stopped) setError(null)
        if (!stopped) timer = setTimeout(refresh, hasActiveWork ? 4_000 : 15_000)
      } catch (err: any) {
        if (!stopped) setError(err?.message || 'Could not load browser jobs.')
        if (!stopped) timer = setTimeout(refresh, 15_000)
      }
    }
    refresh()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  // Polling intentionally owns its refresh cycle; active state is read on each response.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    let disposed = false
    let objectUrl: string | null = null
    const screenshot = [...(activeJob?.artifacts || [])].reverse().find(item => item.kind === 'screenshot')
    if (!screenshot || !activeJob) {
      setScreenshotUrl(null)
      return
    }
    apiBlobUrl(screenshot.download_url).then(url => {
      if (disposed) URL.revokeObjectURL(url)
      else {
        objectUrl = url
        setScreenshotUrl(url)
      }
    }).catch(() => setScreenshotUrl(null))
    return () => {
      disposed = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [activeJob])

  const createJob = async () => {
    setBusy(true)
    setError(null)
    try {
      const created = await api<BrowserJobSummary>('/browser-jobs', {
        method: 'POST',
        headers: { 'Idempotency-Key': globalThis.crypto?.randomUUID?.() || `browser-${Date.now()}` },
        body: JSON.stringify({ start_url: startUrl, goal }),
      })
      await load(created.id)
    } catch (err: any) {
      setError(err?.message || 'Could not start the browser job.')
    } finally {
      setBusy(false)
    }
  }

  const approve = async () => {
    if (!activeJob) return
    setBusy(true)
    try {
      await api(`/browser-jobs/${activeJob.id}/approve`, {
        method: 'POST',
        body: JSON.stringify({ confirmation: 'approve' }),
      })
      await load(activeJob.id)
    } catch (err: any) {
      setError(err?.message || 'Could not approve this browser action.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <h2 className="text-lg font-bold text-primary">Browser worker</h2>
        <p className="text-xs text-muted mt-1">Private artifacts, restricted network access, and approval before external changes.</p>
      </div>

      {error && <div role="alert" className="p-3 rounded-xl border border-red-200 bg-red-50 text-sm text-red-700 dark:bg-red-500/10 dark:border-red-500/20 dark:text-red-300">{error}</div>}

      {capabilities && !capabilities.enabled ? (
        <div className="card p-6">
          <div className="flex items-start gap-3">
            <LockIcon className="w-6 h-6 text-amber-500 shrink-0" />
            <div>
              <p className="text-sm font-semibold text-primary">Browser execution is not enabled on this environment</p>
              <p className="text-xs text-muted mt-1 leading-relaxed">The API and approval workflow are installed, but this deployment has no isolated browser worker. Research continues to use source-reading providers.</p>
            </div>
          </div>
        </div>
      ) : (
        <section className="card p-5 space-y-4">
          <div className="grid gap-3">
            <label className="text-xs text-secondary">Start URL
              <input type="url" value={startUrl} onChange={event => setStartUrl(event.target.value)} placeholder="https://example.com" className="w-full mt-1" />
            </label>
            <label className="text-xs text-secondary">Goal
              <textarea value={goal} onChange={event => setGoal(event.target.value)} rows={2} className="w-full mt-1 resize-none" />
            </label>
          </div>
          <div className="flex items-center justify-between gap-3">
            <p className="text-[10px] text-muted">HTTPS only · no credentials · up to 3 active jobs</p>
            <button onClick={createJob} disabled={busy || !startUrl || !goal} className="btn-primary disabled:opacity-50">
              {busy ? 'Starting…' : 'Start safe inspection'}
            </button>
          </div>
        </section>
      )}

      {activeJob && (
        <section className="card p-5 space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-muted">Current browser job</p>
              <p className="text-sm font-semibold text-primary mt-1">{activeJob.goal}</p>
              <p className="text-[11px] text-muted font-mono truncate mt-1">{activeJob.current_url || activeJob.start_url}</p>
            </div>
            <StatusBadge status={activeJob.status} />
          </div>

          {activeJob.status === 'awaiting_approval' && (
            <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 dark:bg-amber-500/10 dark:border-amber-500/20">
              <p className="text-sm font-medium text-primary">The next action can change external state.</p>
              <p className="text-xs text-muted mt-1">Review the completed steps and screenshot before allowing it.</p>
              <button onClick={approve} disabled={busy} className="btn-primary mt-3 disabled:opacity-50">Approve next action</button>
            </div>
          )}

          <div className="space-y-2">
            {activeJob.steps.map(step => (
              <div key={step.id} className="flex items-center gap-3 rounded-lg bg-hover p-3">
                <span className={`w-2 h-2 rounded-full ${step.status === 'completed' ? 'bg-emerald-500' : step.status === 'failed' ? 'bg-red-500' : step.status === 'awaiting_approval' ? 'bg-amber-500' : 'bg-gray-300'}`} />
                <span className="text-xs font-medium text-primary capitalize">{step.action}</span>
                <span className="text-[10px] text-muted flex-1">{step.status.replace('_', ' ')}</span>
                {step.requires_approval && <span className="text-[9px] text-amber-600">approval gated</span>}
              </div>
            ))}
          </div>

          {screenshotUrl && (
            <div className="rounded-xl overflow-hidden border border-border bg-white">
              <img src={screenshotUrl} alt="Authenticated browser job screenshot" className="w-full h-auto" />
            </div>
          )}
        </section>
      )}

      {jobs.length > 1 && (
        <section className="space-y-2">
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider">Previous browser jobs</h3>
          {jobs.map(job => (
            <button key={job.id} onClick={() => load(job.id)} className="card w-full p-3 flex items-center gap-3 text-left">
              <StatusBadge status={job.status} />
              <span className="text-xs text-secondary truncate flex-1">{job.goal}</span>
              <span className="text-[10px] text-muted">{new Date(job.created_at).toLocaleString()}</span>
            </button>
          ))}
        </section>
      )}
    </div>
  )
}

// === Research Tab ===
function ResearchTab({
  scans,
  activeScan,
  loading,
  error,
  starting,
  onSelect,
  onStart,
  onRetry,
}: {
  scans: ScanSummary[]
  activeScan: ScanDetail | null
  loading: boolean
  error: string | null
  starting: boolean
  onSelect: (scanId: string) => void
  onStart: () => void
  onRetry: () => void
}) {
  const sourceById = new Map((activeScan?.sources || []).map(source => [source.id, source]))
  const isWorking = activeScan?.status === 'queued' || activeScan?.status === 'running'

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-primary">Research & opportunities</h2>
          <p className="text-xs text-muted mt-1">Every recommendation links back to evidence.</p>
        </div>
        <button onClick={onStart} disabled={starting || isWorking}
          className="btn-primary shrink-0 disabled:opacity-50 disabled:cursor-not-allowed">
          {starting ? 'Starting…' : isWorking ? 'Scan running' : 'New scan'}
        </button>
      </div>

      {error && (
        <div role="alert" className="p-3 rounded-xl border border-red-200 bg-red-50 text-sm text-red-700 dark:bg-red-500/10 dark:border-red-500/20 dark:text-red-300">
          {error}
        </div>
      )}

      {loading && !activeScan ? (
        <div className="card p-8 text-center" aria-live="polite">
          <SearchSparkIcon className="w-8 h-8 text-brand mx-auto mb-3 animate-pulse" />
          <p className="text-sm font-medium text-primary">Loading your research…</p>
        </div>
      ) : !activeScan ? (
        <div className="card p-8 text-center">
          <SearchSparkIcon className="w-9 h-9 text-muted mx-auto mb-3" />
          <p className="text-sm font-medium text-primary">No evidence-backed scan yet</p>
          <p className="text-xs text-muted mt-1 mb-5 max-w-sm mx-auto">
            Start a market scan to collect current sources, competitor signals, customer discussions, and ranked actions.
          </p>
          <button onClick={onStart} disabled={starting} className="btn-primary disabled:opacity-50">
            {starting ? 'Starting…' : 'Start first scan'}
          </button>
        </div>
      ) : (
        <>
          <section className="card p-5">
            <div className="flex items-start justify-between gap-3 mb-4">
              <div className="min-w-0">
                <p className="text-[10px] text-muted uppercase tracking-wider mb-1">Latest research</p>
                <h3 className="text-base font-semibold text-primary truncate">{activeScan.product.name}</h3>
                <p className="text-xs text-muted mt-1">{activeScan.product.category}</p>
              </div>
              <StatusBadge status={activeScan.status} />
            </div>

            {isWorking && (
              <div aria-live="polite">
                <div className="flex justify-between text-xs text-secondary mb-2">
                  <span>{activeScan.status === 'queued' ? 'Waiting for a research slot' : 'Collecting and structuring evidence'}</span>
                  <span className="font-mono">{activeScan.progress}%</span>
                </div>
                <div className="h-2 rounded-full bg-border overflow-hidden"
                  role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={activeScan.progress}>
                  <div className="h-full bg-brand rounded-full transition-all duration-700"
                    style={{ width: `${activeScan.progress}%` }} />
                </div>
                <p className="text-[11px] text-muted mt-3">You can leave this page. The job continues on the server.</p>
              </div>
            )}

            {activeScan.status === 'failed' && (
              <div>
                <p className="text-sm text-red-600 dark:text-red-400 mb-3">{activeScan.error || 'The scan stopped before results were saved.'}</p>
                <button onClick={onRetry} disabled={starting} className="btn-primary disabled:opacity-50">
                  {starting ? 'Retrying…' : 'Retry scan'}
                </button>
              </div>
            )}

            {activeScan.status === 'completed' && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <ResearchMetric value={activeScan.summary.source_count || 0} label="Sources" />
                <ResearchMetric value={activeScan.summary.competitor_count || 0} label="Competitors" />
                <ResearchMetric value={activeScan.summary.signal_count || 0} label="Signals" />
                <ResearchMetric value={activeScan.summary.opportunity_count || 0} label="Opportunities" />
              </div>
            )}
          </section>

          {activeScan.status === 'completed' && (
            <>
              <section>
                <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-3 flex items-center gap-2">
                  <ZapIcon className="w-3.5 h-3.5" /> Ranked opportunities
                </h3>
                {activeScan.opportunities.length === 0 ? (
                  <div className="card p-6 text-center">
                    <AlertTriangleIcon className="w-7 h-7 text-amber-500 mx-auto mb-2" />
                    <p className="text-sm font-medium text-primary">Not enough evidence for a recommendation</p>
                    <p className="text-xs text-muted mt-1">Check your research provider configuration, then run another scan.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {activeScan.opportunities.map(opportunity => (
                      <article key={opportunity.id} className="card p-5">
                        <div className="flex items-start gap-3">
                          <span className="w-7 h-7 rounded-full bg-brand/10 text-brand text-xs font-bold flex items-center justify-center shrink-0">
                            {opportunity.rank}
                          </span>
                          <div className="flex-1 min-w-0">
                            <div className="flex flex-wrap gap-2 mb-2">
                              <MetaBadge>{opportunity.channel}</MetaBadge>
                              <MetaBadge>{Math.round(opportunity.confidence * 100)}% confidence</MetaBadge>
                              <MetaBadge>{opportunity.effort} effort</MetaBadge>
                              <MetaBadge>{opportunity.expected_impact} impact</MetaBadge>
                            </div>
                            <h4 className="text-sm font-semibold text-primary leading-snug">{opportunity.title}</h4>
                            <p className="text-xs text-secondary mt-2 leading-relaxed">{opportunity.rationale}</p>
                            <div className="mt-3 p-3 rounded-lg bg-hover">
                              <p className="text-[10px] uppercase tracking-wider text-muted mb-1">Recommended next action</p>
                              <p className="text-sm text-primary">{opportunity.recommended_action}</p>
                            </div>
                            {opportunity.evidence_source_ids.length > 0 && (
                              <div className="flex flex-wrap gap-2 mt-3">
                                {opportunity.evidence_source_ids.map(sourceId => {
                                  const source = sourceById.get(sourceId)
                                  return source ? (
                                    <a key={sourceId} href={source.url} target="_blank" rel="noreferrer"
                                      className="text-[11px] text-brand hover:underline max-w-full truncate">
                                      Source: {source.title || new URL(source.url).hostname}
                                    </a>
                                  ) : null
                                })}
                              </div>
                            )}
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <section>
                <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-3 flex items-center gap-2">
                  <NewsIcon className="w-3.5 h-3.5" /> Evidence collected
                </h3>
                <div className="space-y-2">
                  {activeScan.sources.slice(0, 8).map(source => (
                    <a key={source.id} href={source.url} target="_blank" rel="noreferrer"
                      className="card p-3 flex items-start gap-3 block hover:border-brand/20">
                      <div className="w-8 h-8 rounded-lg bg-brand/8 flex items-center justify-center text-brand shrink-0">
                        {source.type === 'social' ? <BellIcon className="w-4 h-4" /> : <SearchSparkIcon className="w-4 h-4" />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-primary truncate">{source.title || source.url}</p>
                        <p className="text-xs text-muted line-clamp-2 mt-0.5">{source.excerpt || 'Open source'}</p>
                        <p className="text-[10px] text-muted mt-1">{source.platform || source.type} · {Math.round(source.relevance_score * 100)}% relevance</p>
                      </div>
                    </a>
                  ))}
                </div>
              </section>
            </>
          )}

          {scans.length > 1 && (
            <section>
              <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-3">Previous scans</h3>
              <div className="space-y-2">
                {scans.map(scan => (
                  <button key={scan.id} onClick={() => onSelect(scan.id)}
                    aria-current={scan.id === activeScan.id ? 'true' : undefined}
                    className={`w-full p-3 rounded-xl border text-left flex items-center gap-3 transition-colors ${
                      scan.id === activeScan.id ? 'border-brand/30 bg-brand/5' : 'border-border hover:border-brand/20'
                    }`}>
                    <StatusBadge status={scan.status} />
                    <span className="text-xs text-secondary flex-1">{new Date(scan.created_at).toLocaleString()}</span>
                    <span className="text-xs text-muted">{scan.summary.opportunity_count || 0} opportunities</span>
                  </button>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const style = status === 'completed'
    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
    : status === 'failed'
      ? 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300'
      : 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300'
  return <span className={`px-2 py-1 rounded-full text-[10px] font-medium uppercase tracking-wider shrink-0 ${style}`}>{status}</span>
}

function ResearchMetric({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-xl bg-hover p-3 text-center">
      <p className="text-xl font-bold text-primary">{value}</p>
      <p className="text-[10px] text-muted uppercase tracking-wider">{label}</p>
    </div>
  )
}

function MetaBadge({ children }: { children: React.ReactNode }) {
  return <span className="px-2 py-0.5 rounded-full bg-hover text-[10px] text-secondary capitalize">{children}</span>
}

// === Overview Tab ===
function OverviewTab({ goals, pending, unreadCount, reports }: any) {
  return (
    <div className="space-y-6 animate-fade-in">
      {/* 目标进度 */}
      <section>
        <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-3 flex items-center gap-2">
          <TargetIcon className="w-3.5 h-3.5" /> Goals
        </h3>
        {goals?.has_goal ? (
          <div className="card p-5">
            <div className="flex items-baseline gap-2 mb-3">
              <span className="text-3xl font-bold text-primary">{goals.overall_progress || 0}%</span>
              <span className="text-xs text-muted">overall progress</span>
            </div>
            <div className="h-2 rounded-full bg-border overflow-hidden mb-4">
              <div className="h-full bg-brand rounded-full transition-all duration-700"
                style={{ width: `${goals.overall_progress || 0}%` }} />
            </div>
            {goals.objective && (
              <p className="text-sm font-medium text-primary mb-2">{goals.objective}</p>
            )}
            {goals.key_results?.map((kr: any, i: number) => (
              <div key={i} className="flex items-center gap-2 text-xs text-secondary py-1">
                <span className={`w-1.5 h-1.5 rounded-full ${kr.progress >= 100 ? 'bg-emerald-500' : kr.progress >= 50 ? 'bg-brand' : 'bg-gray-300'}`} />
                <span className="flex-1">{kr.description || kr.metric}</span>
                <span className="font-mono text-muted">{kr.progress || 0}%</span>
              </div>
            ))}
            {goals.at_risk?.length > 0 && (
              <div className="mt-3 p-2 rounded-lg bg-red-50 dark:bg-red-500/10 text-xs text-red-600 dark:text-red-400">
                ⚠️ At risk: {goals.at_risk.join(', ')}
              </div>
            )}
          </div>
        ) : (
          <div className="card p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-xl bg-brand/8 flex items-center justify-center">
                <RocketIcon className="w-5 h-5 text-brand" />
              </div>
              <div>
                <p className="text-sm font-medium text-primary">Getting started</p>
                <p className="text-xs text-muted">Tell CrabRes about your product to set growth goals</p>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs text-secondary p-2 rounded-lg bg-hover">
                <span className="w-5 h-5 rounded-full bg-brand/10 flex items-center justify-center text-[10px] font-bold text-brand">1</span>
                <span>Describe your product in the chat</span>
              </div>
              <div className="flex items-center gap-2 text-xs text-secondary p-2 rounded-lg bg-hover">
                <span className="w-5 h-5 rounded-full bg-brand/10 flex items-center justify-center text-[10px] font-bold text-brand">2</span>
                <span>CrabRes researches your market & competitors</span>
              </div>
              <div className="flex items-center gap-2 text-xs text-secondary p-2 rounded-lg bg-hover">
                <span className="w-5 h-5 rounded-full bg-brand/10 flex items-center justify-center text-[10px] font-bold text-brand">3</span>
                <span>Growth playbook & goals auto-generated here</span>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* 快速状态 */}
      <div className="grid grid-cols-3 gap-3">
        <div className="card p-4 text-center">
          <p className="text-2xl font-bold text-primary">{unreadCount}</p>
          <p className="text-[10px] text-muted uppercase">Alerts</p>
        </div>
        <div className="card p-4 text-center">
          <p className="text-2xl font-bold text-primary">{pending.length}</p>
          <p className="text-[10px] text-muted uppercase">Pending</p>
        </div>
        <div className="card p-4 text-center">
          <p className="text-2xl font-bold text-primary">{reports.length}</p>
          <p className="text-[10px] text-muted uppercase">Reports</p>
        </div>
      </div>

      {/* 待审批预览 */}
      {pending.length > 0 && (
        <section>
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-3 flex items-center gap-2">
            <ShieldCheckIcon className="w-3.5 h-3.5" /> Needs your approval
          </h3>
          <div className="space-y-2">
            {pending.slice(0, 3).map((a: any) => (
              <div key={a.id} className="card p-3 flex items-center gap-3">
                <div className={`w-2 h-2 rounded-full ${a.risk === 'high' ? 'bg-red-500' : a.risk === 'medium' ? 'bg-amber-500' : 'bg-emerald-500'}`} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-primary truncate">{a.description}</p>
                  <p className="text-[10px] text-muted">{a.type} · {a.risk} risk</p>
                </div>
                <span className="text-xs text-brand">Review →</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

// === Notifications Tab ===
function NotificationsTab({ notifications, onMarkRead, onMarkAllRead }: any) {
  const typeIcons: Record<string, React.ReactNode> = {
    competitor_change: <SearchSparkIcon className="w-4 h-4 text-blue-500" />,
    rss_discovery: <NewsIcon className="w-4 h-4 text-emerald-500" />,
    action_result: <ChartBarIcon className="w-4 h-4 text-brand" />,
    goal_at_risk: <AlertTriangleIcon className="w-4 h-4 text-amber-500" />,
    daily_reflection: <BrainIcon className="w-4 h-4 text-purple-500" />,
    approval_needed: <LockIcon className="w-4 h-4 text-red-500" />,
    skill_learned: <BrainIcon className="w-4 h-4 text-indigo-500" />,
    system: <GearIcon className="w-4 h-4 text-gray-500" />,
  }

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-muted uppercase tracking-wider">Notifications</h3>
        {notifications.some((n: any) => !n.read) && (
          <button onClick={onMarkAllRead} className="text-xs text-brand hover:underline">Mark all read</button>
        )}
      </div>

      {notifications.length === 0 ? (
        <div className="card p-8 text-center">
          <BellIcon className="w-8 h-8 text-muted mx-auto mb-2" />
          <p className="text-sm text-muted">No notifications yet</p>
          <p className="text-xs text-muted mt-1">Agent discoveries will appear here</p>
        </div>
      ) : (
        <div className="space-y-2">
          {notifications.map((n: any) => (
            <div key={n.id}
              onClick={() => !n.read && onMarkRead(n.id)}
              className={`card p-3 flex items-start gap-3 cursor-pointer transition-all ${
                !n.read ? 'border-brand/20 bg-brand/3' : 'opacity-70'
              }`}>
              <span className="mt-0.5 shrink-0">{typeIcons[n.type] || <PinIcon className="w-4 h-4 text-muted" />}</span>
              <div className="flex-1 min-w-0">
                <p className={`text-sm ${!n.read ? 'font-medium text-primary' : 'text-secondary'}`}>{n.title}</p>
                <p className="text-xs text-muted mt-0.5 line-clamp-2">{n.body}</p>
                <p className="text-[10px] text-muted mt-1">
                  {new Date(n.created_at * 1000).toLocaleString()}
                  {n.delivered_via?.length > 0 && ` · via ${n.delivered_via.join(', ')}`}
                </p>
              </div>
              {!n.read && <span className="w-2 h-2 rounded-full bg-brand shrink-0 mt-1.5" />}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// === Approvals Tab ===
function ApprovalsTab({ pending, onApprove, onReject }: any) {
  return (
    <div className="space-y-4 animate-fade-in">
      <h3 className="text-xs font-medium text-muted uppercase tracking-wider">Pending Approvals</h3>

      {pending.length === 0 ? (
        <div className="card p-8 text-center">
          <CircleCheckIcon className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
          <p className="text-sm text-muted">No pending approvals</p>
          <p className="text-xs text-muted mt-1">Agent will request approval for risky actions</p>
        </div>
      ) : (
        <div className="space-y-3">
          {pending.map((a: any) => (
            <div key={a.id} className="card p-4">
              <div className="flex items-start gap-3 mb-3">
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold ${
                  a.risk === 'high' ? 'bg-red-100 text-red-600 dark:bg-red-500/20' :
                  a.risk === 'medium' ? 'bg-amber-100 text-amber-600 dark:bg-amber-500/20' :
                  'bg-emerald-100 text-emerald-600 dark:bg-emerald-500/20'
                }`}>
                  {a.risk?.[0]?.toUpperCase() || '?'}
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-primary">{a.description}</p>
                  <p className="text-xs text-muted mt-0.5">{a.type} · {a.risk} risk · {new Date(a.created_at * 1000).toLocaleString()}</p>
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => onApprove(a.id)}
                  className="flex-1 py-2 rounded-lg bg-brand text-white text-xs font-medium hover:bg-brand-hover transition-colors">
                  ✓ Approve
                </button>
                <button onClick={() => onReject(a.id)}
                  className="flex-1 py-2 rounded-lg border border-border text-xs font-medium text-muted hover:text-primary hover:border-red-200 transition-colors">
                  ✕ Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// === Reports Tab ===
function ReportsTab({ reports }: any) {
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-muted uppercase tracking-wider">Weekly Reports</h3>
        <button
          onClick={async () => {
            try {
              await api('/weekly-reports/generate', { method: 'POST' })
              window.location.reload()
            } catch {}
          }}
          className="text-xs text-brand hover:underline">
          Generate now
        </button>
      </div>

      {reports.length === 0 ? (
        <div className="card p-8 text-center">
          <ChartBarIcon className="w-8 h-8 text-muted mx-auto mb-2" />
          <p className="text-sm text-muted">No reports yet</p>
          <p className="text-xs text-muted mt-1">Weekly reports auto-generate every Monday</p>
        </div>
      ) : (
        <div className="space-y-3">
          {reports.map((r: any, i: number) => (
            <div key={r.id || i} className="card overflow-hidden">
              <button
                onClick={() => setExpanded(expanded === (r.id || i) ? null : (r.id || i))}
                className="w-full p-4 flex items-center gap-3 text-left hover:bg-hover transition-colors">
                <CalendarIcon className="w-4 h-4 text-muted shrink-0" />
                <div className="flex-1">
                  <p className="text-sm font-medium text-primary">{r.title || `Week of ${r.week || 'Unknown'}`}</p>
                  <p className="text-xs text-muted">{r.executive_summary?.slice(0, 100) || 'Report available'}</p>
                </div>
                <span className="text-xs text-muted">{expanded === (r.id || i) ? '−' : '+'}</span>
              </button>
              {expanded === (r.id || i) && (
                <div className="px-4 pb-4 pt-0 border-t border-border animate-fade-in">
                  <div className="crabres-prose text-sm mt-3">
                    <ReactMarkdown>{r.content || r.executive_summary || 'No content available'}</ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
