/**
 * Landing Page — Warm, premium, focused
 */

import { useEffect } from 'react'
import PixFrontImg from '../assets/pix_fronted.png'

interface LandingProps {
  onGetStarted: () => void
  onLogin: () => void
  onCompare?: () => void
}

export function Landing({ onGetStarted, onLogin }: LandingProps) {
  // 用户打开 Landing Page 时预热后端（Render 免费版冷启动 30-60s）
  useEffect(() => {
    const API = import.meta.env.VITE_API_BASE || '/api'
    fetch(`${API.replace('/api', '')}/`).catch(() => {})
  }, [])

  return (
    <div className="min-h-screen bg-surface">
      {/* Nav */}
      <nav className="max-w-4xl mx-auto flex items-center justify-between px-6 py-5">
        <span className="text-base font-semibold text-primary tracking-tight">CrabRes</span>
        <div className="flex items-center gap-3">
          <button onClick={onLogin} className="text-sm text-secondary hover:text-primary transition-colors">Log in</button>
          <button onClick={onGetStarted} className="text-sm font-medium text-white bg-brand hover:bg-brand-hover px-4 py-2 rounded-lg transition-all">
            Get started free
          </button>
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-2xl mx-auto text-center px-6 pt-16 pb-20">
        <div className="mb-6">
          <img src={PixFrontImg} alt="CrabRes" className="w-16 h-16 mx-auto object-contain" />
        </div>

        <h1 className="text-4xl sm:text-5xl font-bold text-primary tracking-tight leading-[1.15] mb-5">
          You build it.<br />
          <span className="text-gradient">We grow it.</span>
        </h1>

        <p className="text-lg text-secondary max-w-lg mx-auto mb-8 leading-relaxed">
          CrabRes researches <em>your</em> market, links every source, and ranks the
          growth opportunities worth testing next.
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <button onClick={onGetStarted}
            className="text-base font-medium text-white bg-brand hover:bg-brand-hover px-8 py-3.5 rounded-xl transition-all shadow-md hover:shadow-lg">
            Start free — no credit card
          </button>
          <button onClick={onLogin}
            className="text-sm text-secondary hover:text-primary transition-colors px-4 py-3">
            I have an account &rarr;
          </button>
        </div>
      </section>

      {/* 3 differentiators — gradient cards with icons */}
      <section className="max-w-3xl mx-auto px-6 pb-20">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
          {[
            { icon: '◎', title: 'Researches first', desc: 'Finds your competitors, their traffic sources, and where your users hang out — before giving any advice.' },
            { icon: '◉', title: 'Sources attached', desc: 'See the market pages, competitor evidence, and customer discussions behind each conclusion.' },
            { icon: '✦', title: 'Opportunities ranked', desc: 'Compare confidence, effort, and expected impact before choosing what to execute.' },
          ].map((item, i) => (
            <div key={i} className="relative overflow-hidden p-5 rounded-xl border border-border shadow-sm"
              style={{ background: 'linear-gradient(135deg, rgba(194,65,12,0.05) 0%, rgba(29,78,216,0.05) 100%)' }}>
              <div className="text-2xl mb-3 text-gradient font-bold">{item.icon}</div>
              <h3 className="text-sm font-semibold text-primary mb-2">{item.title}</h3>
              <p className="text-sm text-secondary leading-relaxed">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="max-w-2xl mx-auto px-6 pb-20">
        <h2 className="text-2xl font-bold text-primary text-center mb-10">How it works</h2>
        <div className="space-y-6">
          {[
            { step: '1', title: 'Describe your product', desc: 'A one-liner is enough. "AI resume optimizer for job seekers at $9.99/mo."' },
            { step: '2', title: 'We collect market evidence', desc: 'The scan gathers current market pages, competitor signals, and customer discussions.' },
            { step: '3', title: 'We rank opportunities', desc: 'Each opportunity is scored by confidence, effort, and expected impact.' },
            { step: '4', title: 'You choose the next test', desc: 'Review the supporting sources, then turn the strongest opportunity into an action.' },
          ].map((item) => (
            <div key={item.step} className="flex gap-4 items-start">
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold text-white shrink-0 mt-0.5"
                style={{ background: 'linear-gradient(135deg, var(--brand) 0%, var(--accent) 100%)' }}>
                {item.step}
              </div>
              <div>
                <h3 className="text-sm font-semibold text-primary mb-1">{item.title}</h3>
                <p className="text-sm text-secondary leading-relaxed">{item.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Research contract */}
      <section className="max-w-3xl mx-auto px-6 pb-20">
        <h2 className="text-2xl font-bold text-primary text-center mb-3">Every recommendation shows its work</h2>
        <p className="text-sm text-secondary text-center mb-8 max-w-md mx-auto">
          No evidence means no confident recommendation. You can inspect the sources before acting.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {[
            ['1', 'Evidence', 'Source links and captured findings'],
            ['2', 'Assessment', 'Confidence, effort, and impact'],
            ['3', 'Next action', 'A concrete experiment to run'],
          ].map(([number, title, description]) => (
            <div key={number} className="p-4 rounded-xl border border-border bg-[var(--bg-card)] shadow-sm">
              <span className="text-xs font-semibold text-brand">{number}</span>
              <h3 className="text-sm font-semibold text-primary mt-2">{title}</h3>
              <p className="text-xs text-secondary mt-1 leading-relaxed">{description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Comparison */}
      <section className="max-w-2xl mx-auto px-6 pb-20">
        <div className="p-6 rounded-xl border border-border shadow-sm"
          style={{ background: 'linear-gradient(135deg, rgba(194,65,12,0.03) 0%, rgba(29,78,216,0.03) 100%)' }}>
          <h3 className="text-base font-semibold text-primary mb-4">Not another ChatGPT wrapper</h3>
          <div className="space-y-4 text-sm leading-relaxed">
            <div className="p-3 rounded-lg bg-[var(--bg-subtle)]">
              <span className="text-muted text-xs uppercase tracking-wider">ChatGPT</span>
              <p className="text-secondary mt-1">"You should try Reddit marketing and consider SEO for long-term growth."</p>
            </div>
            <div className="p-3 rounded-lg border border-brand/20 bg-brand/3">
              <span className="text-brand text-xs uppercase tracking-wider font-medium">CrabRes</span>
              <p className="text-primary mt-1">"Three customer discussions repeatedly mention slow onboarding. Here are the source links, our confidence level, and a low-effort activation test to run next."</p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="max-w-2xl mx-auto px-6 pb-20 text-center">
        <h2 className="text-2xl font-bold text-primary mb-4">Ready to grow?</h2>
        <p className="text-sm text-secondary mb-6">Tell us about your product and start an evidence-backed market scan.</p>
        <button onClick={onGetStarted}
          className="text-base font-medium text-white bg-brand hover:bg-brand-hover px-8 py-3.5 rounded-xl transition-all shadow-md hover:shadow-lg">
          Start free
        </button>
      </section>

      {/* Footer */}
      <footer className="border-t border-border py-6 text-center">
        <p className="text-xs text-muted">CrabRes &middot; &copy; {new Date().getFullYear()} &middot; Evidence-backed growth research</p>
      </footer>
    </div>
  )
}
