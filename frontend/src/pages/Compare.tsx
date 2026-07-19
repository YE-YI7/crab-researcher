/**
 * CrabRes vs ChatGPT — 对比页面
 * 
 * 调研发现：对比页面转化率是首页的 2-3 倍
 * 因为来这里的人已经在考虑要不要用，只需要最后一推
 */

interface CompareProps {
  onGetStarted: () => void
  onBack: () => void
}

export function Compare({ onGetStarted, onBack }: CompareProps) {
  return (
    <div className="min-h-screen bg-surface bg-grid bg-noise relative z-10">
      {/* Nav */}
      <nav className="flex items-center justify-between px-6 py-4 max-w-5xl mx-auto">
        <button onClick={onBack} className="flex items-center gap-2 text-sm text-muted hover:text-primary transition-colors">
          ← Back
        </button>
        <button onClick={onGetStarted} className="btn-primary !text-sm">
          Try CrabRes free →
        </button>
      </nav>

      <div className="max-w-4xl mx-auto px-4 py-12">
        <h1 className="font-heading text-4xl font-bold text-primary text-center mb-3">
          CrabRes vs ChatGPT
        </h1>
        <p className="text-secondary text-center mb-12 max-w-lg mx-auto">
          ChatGPT is great for brainstorming. CrabRes is built for execution.
          Here's exactly what's different.
        </p>

        {/* 主对比表 */}
        <div className="card overflow-hidden mb-12">
          <div className="grid grid-cols-3 text-sm">
            {/* 表头 */}
            <div className="p-4 font-heading font-semibold text-muted bg-hover">Feature</div>
            <div className="p-4 font-heading font-semibold text-brand bg-brand/5 text-center">CrabRes</div>
            <div className="p-4 font-heading font-semibold text-muted text-center">ChatGPT</div>

            {[
              { feature: 'Researches your specific competitors', crabres: true, chatgpt: false },
              { feature: 'Searches Reddit/HN for your target users', crabres: true, chatgpt: false },
              { feature: 'Remembers your product across sessions', crabres: true, chatgpt: false },
              { feature: 'Tells you if your direction is wrong', crabres: true, chatgpt: false },
              { feature: 'Writes ready-to-publish posts', crabres: true, chatgpt: 'partial' },
              { feature: 'Personalized outreach emails', crabres: true, chatgpt: 'partial' },
              { feature: 'Source-linked market scans', crabres: true, chatgpt: false },
              { feature: 'Monitors competitors 24/7', crabres: true, chatgpt: false },
              { feature: 'Growth plan with KPI tracking', crabres: true, chatgpt: false },
              { feature: 'Budget-aware recommendations', crabres: true, chatgpt: false },
              { feature: 'Auto-discovers growth opportunities', crabres: true, chatgpt: false },
              { feature: 'General knowledge & reasoning', crabres: true, chatgpt: true },
              { feature: 'Code generation', crabres: false, chatgpt: true },
              { feature: 'Image generation', crabres: false, chatgpt: true },
            ].map((row, i) => (
              <div key={i} className="contents">
                <div className={`p-3.5 text-sm text-primary border-t border-border ${i % 2 === 0 ? '' : 'bg-hover/50'}`}>
                  {row.feature}
                </div>
                <div className={`p-3.5 text-center border-t border-border ${i % 2 === 0 ? 'bg-brand/3' : 'bg-brand/5'}`}>
                  {row.crabres === true ? <span className="text-brand font-semibold">✓</span> :
                   row.crabres === false ? <span className="text-muted">—</span> :
                   <span className="text-muted text-xs">Partial</span>}
                </div>
                <div className={`p-3.5 text-center border-t border-border ${i % 2 === 0 ? '' : 'bg-hover/50'}`}>
                  {row.chatgpt === true ? <span className="text-secondary">✓</span> :
                   row.chatgpt === false ? <span className="text-muted">—</span> :
                   <span className="text-muted text-xs">Partial</span>}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 核心区别说明 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-12">
          <div className="card p-6">
            <h3 className="font-heading font-semibold text-primary text-lg mb-3">
              ChatGPT gives advice.
            </h3>
            <p className="text-sm text-secondary leading-relaxed mb-4">
              "You should try Reddit marketing and consider SEO for long-term growth.
              Also look into influencer partnerships."
            </p>
            <p className="text-xs text-muted italic">
              Generic. No research. You still don't know WHERE on Reddit,
              WHICH keywords, or WHO to contact.
            </p>
          </div>
          <div className="card p-6 border-brand/20 card-glow">
            <h3 className="font-heading font-semibold text-brand text-lg mb-3">
              CrabRes gives actions.
            </h3>
            <p className="text-sm text-secondary leading-relaxed mb-4">
              "I found 3 Reddit threads where people are asking for your exact product.
              Here are replies I wrote for each one. I also found @JeffSu posted a 'best tools'
              video without you — here's an email to him."
            </p>
            <p className="text-xs text-brand/70 italic">
              Based on real research. Every post written. Copy, paste, publish.
            </p>
          </div>
        </div>

        {/* Pricing comparison */}
        <div className="card p-6 mb-12">
          <h3 className="font-heading font-semibold text-primary text-lg mb-4 text-center">Pricing</h3>
          <div className="grid grid-cols-2 gap-4 text-center">
            <div>
              <p className="font-heading text-3xl font-bold text-brand">$0-29</p>
              <p className="text-sm text-muted">CrabRes /month</p>
              <p className="text-xs text-secondary mt-2">Free tier + Pro at $29</p>
            </div>
            <div>
              <p className="font-heading text-3xl font-bold text-primary">$20-200</p>
              <p className="text-sm text-muted">ChatGPT /month</p>
              <p className="text-xs text-secondary mt-2">Plus $20, Pro $200, no marketing features</p>
            </div>
          </div>
        </div>

        {/* CTA */}
        <div className="text-center">
          <h2 className="font-heading text-2xl font-bold text-primary mb-4">
            Ready to stop getting advice and start getting users?
          </h2>
          <button onClick={onGetStarted}
            className="btn-primary !text-base !py-3.5 !px-8 !rounded-xl shadow-lg">
            Start free — no credit card →
          </button>
        </div>
      </div>
    </div>
  )
}
