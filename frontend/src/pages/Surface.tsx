/**
 * Surface — CrabRes 主界面
 * 用户每天打开看到的第一个画面。简洁、温暖、有呼吸感。
 */

import { useState, useEffect } from 'react'
import type { CreatureState } from '../components/creature/types'
import { api } from '../lib/api'
import { t, getLang } from '../lib/i18n'
import { SettingsIcon, PenIcon, ChatIcon, ZapIcon, ChartBarIcon, PlaybookIcon, SearchSparkIcon } from '../components/ui/Icons'
import PixImg from '../assets/pix_basic.png'

interface SurfaceProps {
  creature: CreatureState
  onChat: () => void
  onPlan: () => void
  onDashboard?: () => void
  onSettings?: () => void
}

export function Surface({ creature, onChat, onPlan, onDashboard, onSettings }: SurfaceProps) {
  const greeting = getGreeting(creature)
  const [discoveries, setDiscoveries] = useState<any[]>([])
  const [tasks, setTasks] = useState<any[]>([])
  const [stats, setStats] = useState<any>(null)
  const [expSummary, setExpSummary] = useState<any>(null)
  const [recentActions, setRecentActions] = useState<any[]>([])
  const [latestScan, setLatestScan] = useState<any>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const [taskRes, discRes, statRes, expRes, actRes, scanRes] = await Promise.all([
          api<any>('/growth/tasks').catch(() => ({ tasks: [] })),
          api<any>('/growth/discoveries').catch(() => ({ discoveries: [] })),
          api<any>('/growth/stats').catch(() => null),
          api<any>('/growth/experiments/summary').catch(() => null),
          api<any>('/growth/actions').catch(() => ({ actions: [] })),
          api<any>('/scans?limit=1').catch(() => ({ items: [] })),
        ])
        setTasks(taskRes.tasks || [])
        setDiscoveries(discRes.discoveries || [])
        if (statRes) setStats(statRes)
        if (expRes) setExpSummary(expRes)
        setRecentActions((actRes.actions || []).slice(-5).reverse())
        setLatestScan(scanRes.items?.[0] || null)
      } catch {}
    }
    load()
    const interval = setInterval(load, 60_000)
    return () => clearInterval(interval)
  }, [])

  const hasStats = stats?.growth_rate || stats?.total_users || stats?.streak_days || creature.totalUsers > 0

  return (
    <div className="min-h-screen bg-surface flex flex-col items-center px-5 py-8 max-w-lg mx-auto">
      {/* 顶部 */}
      <div className="w-full flex items-center justify-between mb-10">
        <span className="text-base font-semibold text-primary tracking-tight">CrabRes</span>
        <button onClick={onSettings} className="p-2 rounded-lg hover:bg-hover transition-colors text-muted hover:text-primary">
          <SettingsIcon />
        </button>
      </div>

      {/* Pix + 问候 */}
      <div className="flex flex-col items-center mb-8">
        <img src={PixImg} alt="CrabRes" className="w-24 h-24 object-contain mb-4 animate-float" />
        <p className="text-sm text-secondary text-center max-w-xs leading-relaxed">{greeting}</p>
      </div>

      {/* 数字 — 只在有数据时 */}
      {hasStats && (
        <div className="flex items-center gap-8 mb-10">
          <MetricCard value={`+${stats?.growth_rate ?? creature.growthRate}%`} label={t('metric.growth')} />
          <div className="w-px h-8 bg-border" />
          <MetricCard value={`${stats?.total_users ?? creature.totalUsers}`} label={t('metric.users')} />
          <div className="w-px h-8 bg-border" />
          <MetricCard value={`${stats?.streak_days ?? creature.streakDays}d`} label={t('metric.streak')} />
        </div>
      )}

      {/* 主 CTA — 永远可见 */}
      <div className="w-full mb-8">
        <button onClick={onChat}
          className="w-full py-3.5 rounded-xl bg-brand text-white text-sm font-semibold hover:bg-brand-hover transition-all shadow-md">
          {t('surface.talk')}
        </button>
      </div>

      {/* 今日任务 */}
      <div className="w-full mb-6">
        <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-3">
          {t('surface.today')}
        </h3>
        <div className="space-y-2">
          {latestScan && (
            <TaskCard
              icon={<SearchSparkIcon />}
              title={latestScan.status === 'completed'
                ? `${latestScan.summary?.opportunity_count || 0} research opportunities ready`
                : latestScan.status === 'failed'
                  ? 'Research scan needs attention'
                  : `Market research ${latestScan.progress || 0}% complete`}
              subtitle={latestScan.status === 'completed'
                ? `${latestScan.summary?.source_count || 0} sources · evidence attached`
                : 'The scan continues safely on the server'}
              action="View"
              onAction={onDashboard}
            />
          )}
          {tasks.length > 0 ? tasks.map((tk: any, i: number) => (
            <TaskCard
              key={tk.id || i}
              icon={tk.type === 'chat' ? <ChatIcon /> : <PenIcon />}
              title={tk.title}
              subtitle={tk.subtitle || ''}
              action={tk.type === 'chat' ? t('action.chat') : t('action.do')}
              onAction={onChat}
            />
          )) : (
            <TaskCard icon={<ChatIcon />}
              title={t('surface.task.default')}
              subtitle={t('surface.task.default.sub')}
              action={t('action.chat')}
              onAction={onChat} />
          )}
        </div>
      </div>

      {/* 增长实验 — 有数据才显示 */}
      {(expSummary?.total_actions > 0 || recentActions.length > 0) && (
        <div className="w-full mb-6">
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-3 flex items-center gap-2">
            {t('surface.experiments')}
            {expSummary?.total_actions > 0 && (
              <span className="text-[10px] font-mono text-brand bg-brand/8 px-2 py-0.5 rounded-full">
                {expSummary.tracked_actions}/{expSummary.total_actions}
              </span>
            )}
          </h3>
          <div className="space-y-2">
            {recentActions.map((a: any, i: number) => (
              <div key={a.id || i} className="flex items-center gap-3 p-3 rounded-xl border border-border hover:border-brand/20 transition-all">
                <div className="w-8 h-8 rounded-lg bg-brand/8 flex items-center justify-center text-xs font-semibold text-brand uppercase">
                  {(a.platform || '?').slice(0, 2)}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-primary truncate">{a.content_preview || a.url || 'Action recorded'}</p>
                  <p className="text-[10px] text-muted">
                    {a.platform} · {a.status === 'tracked' ? `✓ ${t('common.tracked')}` : t('common.pending')}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 发现 */}
      {discoveries.length > 0 && (
        <div className="w-full mb-6">
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-3">
            {t('surface.discoveries')}
          </h3>
          <div className="space-y-2">
            {discoveries.map((d, i) => (
              <div key={i} className="flex items-center gap-3 p-3 rounded-xl border border-border hover:border-accent/20 transition-all cursor-pointer"
                onClick={() => d.url ? window.open(d.url, '_blank') : onChat()}>
                <div className="w-8 h-8 rounded-lg bg-accent/8 flex items-center justify-center text-accent">
                  <ZapIcon />
                </div>
                <p className="text-sm text-primary flex-1">{d.title || d.change || 'New discovery'}</p>
                <span className="text-xs text-muted">→</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Dashboard + Growth Plan */}
      <div className="w-full space-y-2 mb-8">
        <button onClick={onDashboard}
          className="w-full py-3 rounded-xl border border-brand/20 text-sm font-medium text-brand hover:bg-brand/5 transition-all flex items-center justify-center gap-2">
          <ChartBarIcon className="w-4 h-4" /> Research & Opportunities
        </button>
        <button onClick={onPlan}
          className="w-full py-3 rounded-xl border border-border text-sm font-medium text-primary hover:bg-hover transition-all">
          {t('surface.plan')}
        </button>
      </div>

      {/* 空状态提示 */}
      {!hasStats && discoveries.length === 0 && tasks.length === 0 && !latestScan && (
        <p className="text-xs text-muted text-center mt-4">{t('surface.empty')}</p>
      )}
    </div>
  )
}

// ====== 子组件 ======

function MetricCard({ value, label }: { value: string; label: string }) {
  return (
    <div className="text-center">
      <div className="text-2xl font-bold text-primary tracking-tight">{value}</div>
      <div className="text-[10px] text-muted mt-0.5 uppercase tracking-wider">{label}</div>
    </div>
  )
}

function TaskCard({ icon, title, subtitle, action, onAction }: { icon: React.ReactNode; title: string; subtitle: string; action: string; onAction?: () => void }) {
  return (
    <div className="flex items-center gap-3 p-3.5 rounded-xl border border-border hover:border-brand/20 hover:shadow-sm transition-all group cursor-pointer"
      onClick={onAction}>
      <div className="w-9 h-9 rounded-lg bg-brand/8 flex items-center justify-center text-brand shrink-0">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-primary">{title}</p>
        <p className="text-xs text-muted truncate">{subtitle}</p>
      </div>
      <span className="text-xs text-brand font-medium opacity-0 group-hover:opacity-100 transition-opacity">
        {action} →
      </span>
    </div>
  )
}

// ====== 问候语 ======

function getGreeting(creature: CreatureState): string {
  const hour = new Date().getHours()
  const lang = getLang()

  const greetings = {
    en: {
      morning: [
        `Good morning! ${creature.streakDays} days strong.`,
        `New day, new opportunities.`,
        `Rise and build. Your market is waiting.`,
      ],
      afternoon: [
        `Quick check-in. How's growth going?`,
        `Your growth engine is running. Keep it up.`,
      ],
      evening: [
        `Wrapping up. Here's what happened today.`,
        `Good evening! Tomorrow's plan is ready.`,
      ],
    },
    zh: {
      morning: [
        `早安！连续增长 ${creature.streakDays} 天了。`,
        `新的一天，新的机会。`,
        `起来干活，你的市场在等你。`,
      ],
      afternoon: [
        `下午好，增长进展如何？`,
        `引擎运转中，继续保持。`,
      ],
      evening: [
        `复盘时间。今天发生了这些。`,
        `晚上好！明天的计划已就绪。`,
      ],
    }
  }

  const period = hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening'
  const options = greetings[lang][period]
  const dayHash = new Date().toDateString().split('').reduce((a, b) => a + b.charCodeAt(0), 0)
  return options[dayHash % options.length]
}
