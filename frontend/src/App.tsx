/**
 * CrabRes — AI Growth Strategy Agent
 * 
 * 主应用入口。管理路由和全局状态。
 */

import { useState, useEffect } from 'react'
import { Surface } from './pages/Surface'
import { Chat } from './pages/Chat'
import { Plan } from './pages/Plan'
import { Dashboard } from './pages/Dashboard'
import { Onboarding } from './pages/Onboarding'
import { Landing } from './pages/Landing'
import { Compare } from './pages/Compare'
import { Settings } from './pages/Settings'
import PixFrontImg from './assets/pix_fronted.png'
import { getToken, setToken, clearToken, setAuthExpiredHandler, setColdStartHandler, api } from './lib/api'
import { generateCreature } from './components/creature/types'
import type { CreatureState } from './components/creature/types'

// ====== 登录页（简洁版，后续丰富）======

function AuthPage({ onLogin, initialMode = 'login' }: { onLogin: () => void; initialMode?: 'login' | 'register' }) {
  const [mode, setMode] = useState<'login' | 'register'>(initialMode)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [company, setCompany] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [oauthLoading, setOauthLoading] = useState<'google' | 'github' | null>(null)

  // OAuth 预热跳转：先 ping 后端唤醒，再跳转到 OAuth 地址
  const handleOAuthClick = async (provider: 'google' | 'github') => {
    setOauthLoading(provider)
    setError(null)
    const base = (import.meta as any).env?.VITE_OAUTH_BASE || 'https://crab-researcher.onrender.com/api'
    try {
      // 先 ping 后端唤醒（最多等 45 秒）
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 45000)
      await fetch(`${base}/health`, { signal: controller.signal }).catch(() => {})
      clearTimeout(timeout)
    } catch {}
    // 后端已醒，直接跳转到 OAuth 授权页
    window.location.href = `${base}/oauth/${provider}`
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      if (mode === 'register') {
        const res = await api<{ access_token: string }>('/auth/register', {
          method: 'POST',
          body: JSON.stringify({ company_name: company || 'My Company', contact_email: email, password }),
        })
        setToken(res.access_token)
      } else {
        const res = await api<{ access_token: string }>('/auth/login', {
          method: 'POST',
          body: JSON.stringify({ email, password }),
        })
        setToken(res.access_token)
      }
      onLogin()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <img src={PixFrontImg} alt="CrabRes" className="w-12 h-12 mx-auto mb-2" />
          <h1 className="text-xl font-bold text-primary tracking-tight">CrabRes</h1>
          <p className="text-sm text-muted mt-1">Your AI Growth Partner</p>
        </div>

        {/* OAuth 一键登录 — 先预热后端再跳转，避免 Render 冷启动黑屏 */}
        <div className="space-y-2 mb-4">
          <button onClick={() => handleOAuthClick('google')} disabled={oauthLoading !== null}
            className="flex items-center justify-center gap-2 w-full py-2.5 rounded-lg border border-border text-sm font-medium text-primary hover:bg-hover transition-colors disabled:opacity-60">
            {oauthLoading === 'google' ? (
              <><svg className="animate-spin w-4 h-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Connecting to Google...</>
            ) : (
              <><svg width="16" height="16" viewBox="0 0 24 24"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/></svg> Continue with Google</>
            )}
          </button>
          <button onClick={() => handleOAuthClick('github')} disabled={oauthLoading !== null}
            className="flex items-center justify-center gap-2 w-full py-2.5 rounded-lg border border-border text-sm font-medium text-primary hover:bg-hover transition-colors disabled:opacity-60">
            {oauthLoading === 'github' ? (
              <><svg className="animate-spin w-4 h-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Connecting to GitHub...</>
            ) : (
              <><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.6.11.793-.26.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0 1 12 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/></svg> Continue with GitHub</>
            )}
          </button>
        </div>

        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1 h-px bg-border"></div>
          <span className="text-xs text-muted">or</span>
          <div className="flex-1 h-px bg-border"></div>
        </div>

        {/* 切换 */}
        <div className="flex gap-1 mb-6 p-1 rounded-xl bg-hover">
          <button onClick={() => setMode('login')}
            className={`flex-1 py-2 text-sm font-medium rounded-lg transition-all ${mode === 'login' ? 'bg-white shadow-sm text-primary' : 'text-muted'}`}>
            Log in
          </button>
          <button onClick={() => setMode('register')}
            className={`flex-1 py-2 text-sm font-medium rounded-lg transition-all ${mode === 'register' ? 'bg-white shadow-sm text-primary' : 'text-muted'}`}>
            Sign up
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-xl bg-red-50 border border-red-100 text-sm text-red-600">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          {mode === 'register' && (
            <input
              className="w-full"
              placeholder="Company or product name"
              value={company}
              onChange={e => setCompany(e.target.value)}
            />
          )}
          <input
            className="w-full"
            type="email"
            placeholder="Email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
          />
          <input
            className="w-full"
            type="password"
            placeholder="Password (6+ chars)"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            minLength={6}
          />
          <button type="submit" disabled={loading}
            className="btn-primary w-full !py-3 disabled:opacity-60">
            {loading ? 'Loading...' : mode === 'login' ? 'Log in' : 'Create account'}
          </button>
        </form>

        <p className="text-xs text-muted text-center mt-6">
          {mode === 'login' ? "Don't have an account?" : 'Already have one?'}
          <button onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null) }}
            className="text-brand ml-1 hover:underline">
            {mode === 'login' ? 'Sign up' : 'Log in'}
          </button>
        </p>

        {/* 背书 */}
        <div className="mt-8 text-center">
          <p className="text-xs text-muted">
            Powered by 13 AI growth experts · 18 research frameworks
          </p>
        </div>
      </div>
    </div>
  )
}

// ====== 主应用 ======

export default function App() {
  const [authed, setAuthed] = useState(!!getToken())
  const [showAuth, setShowAuth] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'register'>('register')
  const [showCompare, setShowCompare] = useState(false)
  const [onboarded, setOnboarded] = useState(!!localStorage.getItem('crabres_onboarded'))
  const [page, setPage] = useState<'surface' | 'chat' | 'plan' | 'dashboard' | 'settings'>('surface')
  const [userId, setUserId] = useState('default')
  const [creature, setCreature] = useState<CreatureState>(() =>
    generateCreature('default', 'saas')
  )
  const [serverWaking, setServerWaking] = useState(false)

  useEffect(() => {
    setAuthExpiredHandler(() => setAuthed(false))
    setColdStartHandler((waking) => setServerWaking(waking))
    // 初始化暗色模式
    const savedTheme = localStorage.getItem('crabres_theme')
    if (savedTheme === 'dark') {
      document.documentElement.classList.add('dark')
    }
    // 处理 OAuth 回调（URL 带 #token=xxx，fragment 不会被发到服务器）
    const hash = window.location.hash
    if (hash.startsWith('#token=')) {
      const oauthToken = hash.slice(7)
      if (oauthToken) {
        setToken(oauthToken)
        setAuthed(true)
        window.history.replaceState({}, '', window.location.pathname)
      }
    }
  }, [])

  // 登录后加载用户数据
  useEffect(() => {
    if (!authed) return
    api<any>('/auth/me').then(user => {
      setUserId(String(user.id))
      // 如果已 onboarded，直接加载生物体
      if (onboarded) {
        const savedType = localStorage.getItem('crabres_product_type') || 'saas'
        const c = generateCreature(String(user.id), savedType)
        c.name = localStorage.getItem('crabres_product_name') || user.company_name || 'My Product'
        c.mood = 'happy'
        c.totalUsers = 0
        c.growthRate = 0
        c.streakDays = 0
        setCreature(c)
      }
    }).catch(() => {})
  }, [authed, onboarded])

  // 冷启动提示 Banner
  const ColdStartBanner = serverWaking ? (
    <div className="fixed top-0 left-0 right-0 z-50 bg-brand/90 text-white text-center py-2 text-sm animate-pulse">
      🦀 Server is waking up... This may take 30-60 seconds on free tier.
    </div>
  ) : null

  if (!authed) {
    if (showAuth) {
      return <>{ColdStartBanner}<AuthPage initialMode={authMode} onLogin={() => { setAuthed(true); setShowAuth(false) }} /></>
    }
    if (showCompare) {
      return <Compare onGetStarted={() => { setShowCompare(false); setAuthMode('register'); setShowAuth(true) }} onBack={() => setShowCompare(false)} />
    }
    return <Landing onGetStarted={() => { setAuthMode('register'); setShowAuth(true) }} onLogin={() => { setAuthMode('login'); setShowAuth(true) }} onCompare={() => setShowCompare(true)} />
  }

  // 未完成 onboarding
  if (!onboarded) {
    return (
      <Onboarding
        userId={userId}
        onComplete={(c, productData) => {
          setCreature({ ...c, market: productData.market })
          localStorage.setItem('crabres_onboarded', '1')
          localStorage.setItem('crabres_product_type', productData.type || 'saas')
          localStorage.setItem('crabres_product_name', productData.name || '')
          localStorage.setItem('crabres_product_market', productData.market || 'global')
          setOnboarded(true)
        }}
      />
    )
  }

  if (page === 'chat') {
    return <Chat creature={creature} onBack={() => setPage('surface')} onPlan={() => setPage('plan')} />
  }

  if (page === 'plan') {
    return <Plan creature={creature} onBack={() => setPage('surface')} />
  }

  if (page === 'dashboard') {
    return <Dashboard creature={creature} onBack={() => setPage('surface')} />
  }

  if (page === 'settings') {
    return <Settings creature={creature} onBack={() => setPage('surface')} onLogout={() => { setAuthed(false); setOnboarded(false) }} />
  }

  return (
    <Surface
      creature={creature}
      onChat={() => setPage('chat')}
      onPlan={() => setPage('plan')}
      onDashboard={() => setPage('dashboard')}
      onSettings={() => setPage('settings')}
    />
  )
}
