/**
 * Onboarding — 4步引导流
 * 
 * 注册后进入。收集产品信息，生成生物体，开始研究。
 * 只收集生成第一份有证据增长扫描所需的信息。
 */

import { useState } from 'react'
import PixFrontImg from '../assets/pix_fronted.png'
import PixHappyImg from '../assets/pix_happy.png'
import { generateCreature, SPECIES_CONFIG } from '../components/creature/types'
import type { CreatureState } from '../components/creature/types'
import { api } from '../lib/api'

interface OnboardingProps {
  userId: string
  onComplete: (creature: CreatureState, productData: any) => void
}

const PRODUCT_TYPES = [
  { value: 'saas', label: 'SaaS / Software', icon: '💻' },
  { value: 'tool', label: 'Developer Tool', icon: '🔧' },
  { value: 'ecommerce', label: 'E-commerce', icon: '🛒' },
  { value: 'community', label: 'Community / Social', icon: '👥' },
  { value: 'content', label: 'Content / Media', icon: '◉' },
  { value: 'education', label: 'Education', icon: '📚' },
  { value: 'creative', label: 'Creative / Design', icon: '◎' },
  { value: 'finance', label: 'Finance / Fintech', icon: '◇' },
  { value: 'game', label: 'Gaming / Entertainment', icon: '🎮' },
  { value: 'other', label: 'Other', icon: '✨' },
]

const USER_GOALS = [
  { value: '100', label: '100 users' },
  { value: '500', label: '500 users' },
  { value: '1000', label: '1,000 users' },
  { value: '5000', label: '5,000 users' },
  { value: '10000', label: '10,000+' },
]

const BUDGETS = [
  { value: '0', label: '$0 (time only)' },
  { value: '100', label: '$100/mo' },
  { value: '500', label: '$500/mo' },
  { value: '1000', label: '$1,000+/mo' },
]

const MARKETS = [
  { 
    value: 'global', 
    label: 'English-speaking markets',
    icon: '🌐',
    desc: 'Research English-language communities, competitors, and early adopters.',
    aha: 'Your first scan starts only after you confirm below.'
  },
  { 
    value: 'domestic', 
    label: 'Chinese & international markets',
    icon: '◇',
    desc: '研究中文市场、出海机会和海外用户需求。',
    aha: '确认后才会开始真实研究，不会预先生成通用结论。'
  },
]

export function Onboarding({ userId, onComplete }: OnboardingProps) {
  const [step, setStep] = useState(1)
  const [market, setMarket] = useState('global')
  const [productName, setProductName] = useState('')
  const [productUrl, setProductUrl] = useState('')
  const [productDesc, setProductDesc] = useState('')
  const [productType, setProductType] = useState('')
  const [userGoal, setUserGoal] = useState('')
  const [budget, setBudget] = useState('')
  const [loading, setLoading] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const [creature, setCreature] = useState<CreatureState | null>(null)
  const [createdProductId, setCreatedProductId] = useState<number | null>(null)
  const [scanRequestKey] = useState(() =>
    globalThis.crypto?.randomUUID?.() || `onboarding-${Date.now()}-${Math.random().toString(36).slice(2)}`
  )

  const handleStep1Next = () => {
    if (!productName.trim()) return
    setStep(2)
  }

  const handleStep2Next = () => {
    if (!productDesc.trim() || !productType) return
    setStep(3)
  }

  const handleStep3Next = () => {
    if (!userGoal || !budget) return
    setStep(4)
    // 生成生物体
    const c = generateCreature(userId, productType || 'default')
    c.name = productName
    c.mood = 'waving'
    setCreature(c)
  }

  const handleFinish = async () => {
    setLoading(true)
    setStartError(null)
    const productData = {
      name: productName,
      market,
      url: productUrl,
      description: productDesc,
      type: productType,
      goal_users: userGoal,
      monthly_budget: budget,
      product_id: null as number | null,
      scan_id: '',
    }

    try {
      let productId = createdProductId
      if (!productId) {
        const product = await api<{ id: number }>('/products', {
          method: 'POST',
          body: JSON.stringify({
            product_name: productName.trim(),
            industry: PRODUCT_TYPES.find(item => item.value === productType)?.label || productType,
            category: productDesc.trim().slice(0, 100),
            keywords: [productName.trim(), productType, ...productDesc.trim().split(/\s+/).slice(0, 5)]
              .filter(Boolean),
            price_range: {},
            platforms: market === 'domestic'
              ? ['xiaohongshu', 'zhihu', 'bilibili']
              : ['reddit', 'hackernews', 'producthunt'],
          }),
        })
        productId = product.id
        setCreatedProductId(productId)
      }

      const scan = await api<{ id: string }>('/scans', {
        method: 'POST',
        headers: { 'Idempotency-Key': scanRequestKey },
        body: JSON.stringify({
          product_id: productId,
          scan_type: 'market_landscape',
          locale: market === 'domestic' ? 'zh-CN' : 'en',
          platforms: market === 'domestic'
            ? ['xiaohongshu', 'zhihu', 'bilibili']
            : ['reddit', 'hackernews', 'producthunt'],
        }),
      })
      productData.product_id = productId
      productData.scan_id = scan.id
    } catch (e: any) {
      setStartError(e?.message || 'Could not start the first research scan. Please try again.')
      setLoading(false)
      return
    }

    const c = creature || generateCreature(userId, productType || 'default')
    c.name = productName
    onComplete(c, productData)
  }

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center px-4">
      <div className="w-full max-w-md">

        {/* 进度指示 */}
        <div className="flex items-center gap-2 mb-8 justify-center">
          {[1, 2, 3, 4].map(s => (
            <div key={s} className="flex items-center gap-2">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-all ${
                s === step ? 'bg-brand text-white' :
                s < step ? 'bg-brand/20 text-brand' :
                'bg-hover text-muted'
              }`}>
                {s < step ? '✓' : s}
              </div>
              {s < 4 && <div className={`w-8 h-px ${s < step ? 'bg-brand' : 'bg-border'}`} />}
            </div>
          ))}
        </div>

        {/* Step 1: 市场焦点 & 名称 */}
        {step === 1 && (
          <div className="text-center">
            <div className="text-4xl mb-3">🦀</div>
            <h2 className="text-xl font-bold text-primary mb-1">
              {market === 'global' ? 'Choose your growth focus' : '选择你的增长重心'}
            </h2>
            <p className="text-sm text-muted mb-6">
              {market === 'global' ? 'I will tailor my expertise to your persona.' : '我会根据你的画像定制增长策略。'}
            </p>

            <div className="space-y-3 text-left mb-6">
              {MARKETS.map(m => (
                <button
                  key={m.value}
                onClick={() => setMarket(m.value)}
                  aria-pressed={market === m.value}
                  className={`w-full p-4 rounded-xl text-left border transition-all ${
                    market === m.value
                      ? 'border-brand bg-brand/10 shadow-glow'
                      : 'border-white/5 bg-card hover:border-brand/30'
                  }`}
                >
                  <div className="flex items-center gap-3 mb-1">
                    <span className="text-2xl">{m.icon}</span>
                    <span className={`font-bold tracking-tight ${market === m.value ? 'text-brand' : 'text-primary'}`}>{m.label}</span>
                  </div>
                  <p className="text-xs text-muted leading-relaxed pl-9">{m.desc}</p>
                </button>
              ))}
            </div>

            <div className="text-left mb-6">
              <label className="text-xs font-medium text-secondary mb-1 block">
                {market === 'global' ? 'What is your product name? *' : '你的产品名称是？ *'}
              </label>
              <input
                className="w-full"
                placeholder="e.g., JobPilot"
                value={productName}
                onChange={e => setProductName(e.target.value)}
                autoFocus
              />
            </div>

            <button onClick={handleStep1Next} disabled={!productName.trim()}
              className="btn-primary w-full mt-2 !py-3 disabled:opacity-40">
              {market === 'global' ? 'Next →' : '下一步 →'}
            </button>
          </div>
        )}

        {/* Step 2: 产品详情 */}
        {step === 2 && (
          <div className="text-center">
            <div className="text-4xl mb-3">🛠</div>
            <h2 className="text-xl font-bold text-primary mb-1">
              {market === 'global' ? 'A few more details' : '再补充一些细节'}
            </h2>
            <p className="text-sm text-muted mb-6">
              {market === 'global' ? 'The more I know, the better I research.' : '我知道的越多，研究就越精准。'}
            </p>

            <div className="space-y-3 text-left">
              <div>
                <label className="text-xs font-medium text-secondary mb-1 block">
                  {market === 'global' ? 'What does it do? *' : '它是做什么的？ *'}
                </label>
                <input
                  className="w-full"
                  placeholder={market === 'global' ? "e.g., AI resume optimizer" : "例如：AI 简历优化工具"}
                  value={productDesc}
                  onChange={e => setProductDesc(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-secondary mb-1 block">
                  {market === 'global' ? 'Product URL (optional)' : '产品 URL (可选)'}
                </label>
                <input
                  className="w-full"
                  placeholder="https://..."
                  value={productUrl}
                  onChange={e => setProductUrl(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-secondary mb-1 block">
                  {market === 'global' ? 'Product type *' : '产品类型 *'}
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {PRODUCT_TYPES.map(t => (
                    <button
                      key={t.value}
                      onClick={() => setProductType(t.value)}
                      aria-pressed={productType === t.value}
                      className={`p-2.5 rounded-xl text-left text-sm border transition-all ${
                        productType === t.value
                          ? 'border-brand bg-brand/10 text-brand font-bold'
                          : 'border-white/5 bg-card text-secondary hover:border-brand/30'
                      }`}
                    >
                      <span className="mr-1.5">{t.icon}</span>{t.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setStep(1)} className="btn-ghost flex-1 !py-3">
                {market === 'global' ? '← Back' : '← 返回'}
              </button>
              <button onClick={handleStep2Next} disabled={!productDesc.trim() || !productType}
                className="btn-primary flex-1 !py-3 disabled:opacity-40">
                {market === 'global' ? 'Next →' : '下一步 →'}
              </button>
            </div>
          </div>
        )}

        {/* Step 3: 目标 */}
        {step === 3 && (
          <div className="text-center">
            <div className="text-2xl mb-3 font-semibold text-brand">◎</div>
            <h2 className="text-xl font-bold text-primary mb-1">
              {market === 'global' ? "What's your growth goal?" : '你的增长目标是？'}
            </h2>
            <p className="text-sm text-muted mb-6">
              {market === 'global' ? 'This helps me calibrate the strategy.' : '这能帮我校准增长策略。'}
            </p>

            <div className="space-y-4 text-left">
              <div>
                <label className="text-xs font-medium text-secondary mb-2 block">
                  {market === 'global' ? 'Target users in 3 months *' : '3 个月内的目标用户数 *'}
                </label>
                <div className="flex flex-wrap gap-2">
                  {USER_GOALS.map(g => (
                    <button
                      key={g.value}
                      onClick={() => setUserGoal(g.value)}
                      aria-pressed={userGoal === g.value}
                      className={`px-4 py-2 rounded-xl text-sm border transition-all ${
                        userGoal === g.value
                          ? 'border-brand bg-brand/5 text-brand font-medium'
                          : 'border-border text-secondary hover:border-brand/30'
                      }`}
                    >
                      {g.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-secondary mb-2 block">
                  {market === 'global' ? 'Monthly marketing budget *' : '月度营销预算 *'}
                </label>
                <div className="flex flex-wrap gap-2">
                  {BUDGETS.map(b => (
                    <button
                      key={b.value}
                      onClick={() => setBudget(b.value)}
                      aria-pressed={budget === b.value}
                      className={`px-4 py-2 rounded-xl text-sm border transition-all ${
                        budget === b.value
                          ? 'border-brand bg-brand/5 text-brand font-medium'
                          : 'border-border text-secondary hover:border-brand/30'
                      }`}
                    >
                      {b.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setStep(2)} className="btn-ghost flex-1 !py-3">
                {market === 'global' ? '← Back' : '← 返回'}
              </button>
              <button onClick={handleStep3Next} disabled={!userGoal || !budget}
                className="btn-primary flex-1 !py-3 disabled:opacity-40">
                {market === 'global' ? 'Next →' : '下一步 →'}
              </button>
            </div>
          </div>
        )}

        {/* Step 4: 生物体揭晓 */}
        {step === 4 && creature && (
          <div className="text-center">
            <h2 className="text-xl font-bold text-primary mb-2">
              {market === 'global' ? 'Meet your growth companion' : '遇见你的增长伙伴'}
            </h2>
            <p className="text-sm text-muted mb-6">
              {market === 'global' 
                ? 'Review the evidence pipeline for your first scan.'
                : '确认首次扫描将收集和评估的证据。'}
            </p>

            <div className="mb-4">
              <img src={PixHappyImg} alt="CrabRes" className="w-32 h-32 object-contain" />
            </div>

            <div className="mb-6">
              <p className="text-lg font-bold" style={{ color: "var(--brand)" }}>
                {market === 'global' 
                  ? 'Your Growth Companion'
                  : '你的增长伙伴'}
              </p>
              <p className="text-sm text-muted mt-1 px-4">
                {market === 'global' 
                  ? 'Research has not started yet. Continue to begin an evidence-backed market scan.'
                  : '研究尚未开始。确认后将启动基于真实来源的市场扫描。'}
              </p>
            </div>

            {/* 扫描管线 */}
            <div className="space-y-1.5 text-left max-w-xs mx-auto mb-6">
              {[
                'Current market sources',
                'Competitor evidence',
                'Customer discussions',
                'Ranked growth opportunities',
              ].map((expert, i) => (
                <div key={i} className="flex items-center gap-2 text-xs animate-fade-in"
                  style={{ animationDelay: `${i * 100}ms`, opacity: 0, animationFillMode: 'forwards' }}>
                  <span className="text-brand">·</span>
                  <span className="text-secondary">{expert}</span>
                  <span className="text-muted">{market === 'global' ? 'ready' : '已就绪'}</span>
                </div>
              ))}
            </div>

            {startError && (
              <p role="alert" className="text-sm text-red-500 mb-3">{startError}</p>
            )}

            <button onClick={handleFinish} disabled={loading}
              className="btn-primary w-full !py-3 disabled:opacity-60">
              {loading 
                ? (market === 'global' ? 'Starting research...' : '开始深度研究...') 
                : (market === 'global' ? "Let's grow! →" : '立即增长！ →')}
            </button>
            
            <p className="text-[10px] text-muted mt-4 uppercase tracking-widest opacity-60">
              {MARKETS.find(m => m.value === market)?.aha}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
