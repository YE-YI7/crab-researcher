/**
 * Workspace — 文件管理 + 文档查看器 + 执行日志
 *
 * 设计：与 CrabRes 暖色系一致，不用 emoji
 * 三个区域：文件树（左）、文档查看器（中）、底部工具栏
 */

import { useState, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import { api, apiBlobUrl } from '../../lib/api'
import {
  FolderIcon, FileTextIcon, FileCodeIcon, CloseIcon,
  TerminalIcon, GlobeSmallIcon, TrashIcon, RefreshIcon,
} from './WorkspaceIcons'

// ====== 类型 ======

interface FileNode {
  name: string
  path: string
  type: 'file' | 'directory'
  size?: number
  extension?: string
  children?: FileNode[]
}

interface OpenTab {
  path: string
  name: string
  content: string
  extension: string
}

interface LogEntry {
  id: string
  type: 'terminal' | 'browser' | 'action'
  content: string
  timestamp: number
}

interface BrowserState {
  status: 'idle' | 'loading' | 'loaded' | 'error'
  url?: string
  title?: string
  screenshotPath?: string
  contentPreview?: string
  error?: string
  engine?: string       // "jina_reader" | "playwright" | "httpx"
  browseFile?: string   // 浏览内容保存的文件路径
}

interface WorkspaceProps {
  /** 是否可见 */
  visible: boolean
  /** 从聊天消息中点击文件时传入 */
  initialFile?: string | null
  /** Agent 执行日志流 */
  logs?: LogEntry[]
  /** 变化时自动刷新文件树（从 Chat 组件传入） */
  refreshKey?: number
  /** 浏览器实时状态（从 Chat 组件传入） */
  browserState?: BrowserState
}

export function Workspace({ visible, initialFile, logs = [], refreshKey = 0, browserState }: WorkspaceProps) {
  const [tree, setTree] = useState<FileNode[]>([])
  const [tabs, setTabs] = useState<OpenTab[]>([])
  const [activeTab, setActiveTab] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [bottomTab, setBottomTab] = useState<'files' | 'terminal' | 'preview'>('files')
  const [stats, setStats] = useState<any>(null)
  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(null)

  useEffect(() => {
    const screenshotPath = browserState?.screenshotPath
    if (!visible || !screenshotPath) {
      setScreenshotUrl(null)
      return
    }
    let active = true
    let objectUrl: string | null = null
    const filename = screenshotPath.split('/').pop()
    apiBlobUrl(`/workspace/files/read?path=${encodeURIComponent(`assets/${filename}`)}`)
      .then(url => {
        objectUrl = url
        if (active) setScreenshotUrl(url)
      })
      .catch(() => active && setScreenshotUrl(null))
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [visible, browserState?.screenshotPath])

  // 加载文件树
  const loadTree = useCallback(async () => {
    try {
      const res = await api<any>('/workspace/files/tree')
      setTree(res.tree || [])
    } catch {}
  }, [])

  const loadStats = useCallback(async () => {
    try {
      const res = await api<any>('/workspace/stats')
      setStats(res)
    } catch {}
  }, [])

  useEffect(() => {
    if (visible) {
      loadTree()
      loadStats()
    }
  }, [visible, loadTree, loadStats])

  // refreshKey 变化时自动刷新文件树（由 Chat 组件的 file_created 事件触发）
  useEffect(() => {
    if (visible && refreshKey > 0) {
      loadTree()
      loadStats()
    }
  }, [refreshKey])

  // 处理从聊天中点击的文件
  useEffect(() => {
    if (initialFile && visible) {
      openFile(initialFile)
    }
  }, [initialFile, visible])

  // 打开文件
  const openFile = async (path: string) => {
    // 已打开则切换
    const existing = tabs.find(t => t.path === path)
    if (existing) {
      setActiveTab(path)
      return
    }

    setLoading(true)
    try {
      const res = await api<any>(`/workspace/files/read?path=${encodeURIComponent(path)}`)
      const newTab: OpenTab = {
        path: res.path,
        name: res.name,
        content: res.content,
        extension: res.extension || 'md',
      }
      setTabs(prev => [...prev, newTab])
      setActiveTab(path)
    } catch {} finally {
      setLoading(false)
    }
  }

  // 关闭 Tab
  const closeTab = (path: string) => {
    setTabs(prev => prev.filter(t => t.path !== path))
    if (activeTab === path) {
      setActiveTab(tabs.length > 1 ? tabs[tabs.length - 2]?.path || null : null)
    }
  }

  // 删除文件
  const deleteFile = async (path: string) => {
    try {
      await api(`/workspace/files?path=${encodeURIComponent(path)}`, { method: 'DELETE' })
      closeTab(path)
      loadTree()
      loadStats()
    } catch {}
  }

  const activeContent = tabs.find(t => t.path === activeTab)

  if (!visible) return null

  return (
    <div className="flex flex-col h-full bg-surface border-l border-border">
      {/* ====== Tab 栏 ====== */}
      <div className="flex items-center border-b border-border bg-[var(--bg-secondary)] shrink-0 min-h-[37px]">
        {tabs.length === 0 ? (
          <div className="px-4 py-2 text-xs text-muted">No files open</div>
        ) : (
          <div className="flex-1 flex overflow-x-auto">
            {tabs.map(tab => (
              <div key={tab.path}
                className={`flex items-center gap-1.5 px-3 py-2 text-xs cursor-pointer border-r border-border shrink-0 transition-colors ${
                  activeTab === tab.path
                    ? 'bg-surface text-primary border-b-2 border-b-brand'
                    : 'text-muted hover:text-primary hover:bg-surface/50'
                }`}
                onClick={() => setActiveTab(tab.path)}>
                <FileIcon ext={tab.extension} />
                <span className="max-w-[120px] truncate">{tab.name}</span>
                <button
                  onClick={(e) => { e.stopPropagation(); closeTab(tab.path) }}
                  className="ml-1 p-0.5 rounded hover:bg-hover opacity-0 group-hover:opacity-100 hover:opacity-100 transition-opacity"
                  style={{ opacity: activeTab === tab.path ? 0.6 : 0 }}>
                  <CloseIcon className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        <button onClick={() => { loadTree(); loadStats() }}
          className="p-2 text-muted hover:text-primary transition-colors shrink-0">
          <RefreshIcon className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* ====== 主内容区 ====== */}
      <div className="flex-1 flex min-h-0">
        {/* 左侧文件树 */}
        <div className="w-[200px] shrink-0 border-r border-border overflow-y-auto bg-[var(--bg-secondary)]">
          <div className="px-3 py-2 flex items-center justify-between">
            <span className="text-[10px] font-medium text-muted uppercase tracking-wider">Workspace</span>
            {stats?.total_files > 0 && (
              <span className="text-[9px] text-muted font-mono">{stats.total_files} files</span>
            )}
          </div>
          {tree.length === 0 ? (
            <div className="px-3 py-8 text-center">
              <FolderIcon className="w-8 h-8 text-muted mx-auto mb-2 opacity-40" />
              <p className="text-[11px] text-muted">No files yet</p>
              <p className="text-[10px] text-muted mt-1">Chat with CrabRes to generate reports</p>
            </div>
          ) : (
            <div className="pb-4">
              {tree.map(node => (
                <TreeNode key={node.path} node={node} depth={0}
                  activeFile={activeTab}
                  onOpen={openFile}
                  onDelete={deleteFile} />
              ))}
            </div>
          )}
        </div>

        {/* 右侧文档查看器 */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* 文档内容 */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center h-full text-sm text-muted">
                Loading...
              </div>
            ) : activeContent ? (
              <div className="p-6 max-w-3xl">
                {activeContent.extension === 'md' ? (
                  <div className="crabres-prose">
                    <ReactMarkdown>{activeContent.content}</ReactMarkdown>
                  </div>
                ) : activeContent.extension === 'json' ? (
                  <pre className="text-xs font-mono text-secondary leading-relaxed whitespace-pre-wrap">
                    {(() => {
                      try { return JSON.stringify(JSON.parse(activeContent.content), null, 2) }
                      catch { return activeContent.content }
                    })()}
                  </pre>
                ) : (
                  <pre className="text-xs font-mono text-secondary leading-relaxed whitespace-pre-wrap">
                    {activeContent.content}
                  </pre>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-center px-8">
                <div className="w-12 h-12 rounded-xl bg-brand/8 flex items-center justify-center mb-3">
                  <FileTextIcon className="w-6 h-6 text-brand opacity-50" />
                </div>
                <p className="text-sm font-medium text-muted mb-1">Select a file to view</p>
                <p className="text-xs text-muted max-w-[240px]">
                  Files generated by CrabRes appear in the tree on the left
                </p>
              </div>
            )}
          </div>

          {/* ====== 底部工具栏 ====== */}
          <div className="shrink-0 border-t border-border bg-[var(--bg-secondary)]">
            {/* 工具栏 Tab */}
            <div className="flex items-center border-b border-border">
              {([
                { key: 'files' as const, label: 'Files', icon: <FolderIcon className="w-3.5 h-3.5" /> },
                { key: 'terminal' as const, label: 'Agent Log', icon: <TerminalIcon className="w-3.5 h-3.5" /> },
                { key: 'preview' as const, label: 'Browser', icon: <GlobeSmallIcon className="w-3.5 h-3.5" /> },
              ]).map(t => (
                <button key={t.key}
                  onClick={() => setBottomTab(t.key)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium transition-colors border-b-2 ${
                    bottomTab === t.key
                      ? 'text-primary border-brand'
                      : 'text-muted border-transparent hover:text-primary'
                  }`}>
                  {t.icon} {t.label}
                </button>
              ))}
            </div>

            {/* 工具栏内容 */}
            <div className="h-[120px] overflow-y-auto p-2">
              {bottomTab === 'files' && (
                <div className="space-y-0.5">
                  {stats?.categories && Object.entries(stats.categories).map(([cat, count]) => (
                    <div key={cat} className="flex items-center gap-2 px-2 py-1 text-xs text-secondary">
                      <FolderIcon className="w-3.5 h-3.5 text-muted" />
                      <span className="flex-1">{cat}</span>
                      <span className="text-muted font-mono">{count as number}</span>
                    </div>
                  ))}
                  {(!stats?.categories || Object.keys(stats.categories).length === 0) && (
                    <p className="text-[11px] text-muted px-2 py-4 text-center">No workspace files yet</p>
                  )}
                </div>
              )}
              {bottomTab === 'terminal' && (
                <div className="font-mono text-[11px] leading-relaxed space-y-0.5">
                  {logs.length === 0 ? (
                    <p className="text-muted px-1 py-4 text-center font-sans">Agent execution log will appear here</p>
                  ) : (
                    logs.map(log => (
                      <div key={log.id} className="flex gap-2 px-1">
                        <span className="text-muted shrink-0">
                          {new Date(log.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        </span>
                        <span className={
                          log.type === 'action' ? 'text-brand' :
                          log.type === 'browser' ? 'text-blue-500' :
                          'text-secondary'
                        }>{log.content}</span>
                      </div>
                    ))
                  )}
                </div>
              )}
              {bottomTab === 'preview' && (
                <div className="h-full overflow-y-auto">
                  {(!browserState || browserState.status === 'idle') ? (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <GlobeSmallIcon className="w-6 h-6 text-muted mx-auto mb-1 opacity-40" />
                        <p className="text-[11px] text-muted">Browser preview</p>
                        <p className="text-[10px] text-muted mt-0.5">Shows when Agent navigates websites</p>
                      </div>
                    </div>
                  ) : browserState.status === 'loading' ? (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <div className="w-6 h-6 border-2 border-brand/30 border-t-brand rounded-full animate-spin mx-auto mb-2" />
                        <p className="text-[11px] text-primary font-medium">Navigating...</p>
                        <p className="text-[10px] text-muted mt-0.5 font-mono max-w-[300px] truncate">{browserState.url}</p>
                      </div>
                    </div>
                  ) : browserState.status === 'loaded' ? (
                    <div className="p-2 space-y-2">
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
                        <span className="text-[11px] font-medium text-primary truncate">{browserState.title || 'Page loaded'}</span>
                        {browserState.engine && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-brand/10 text-brand font-mono shrink-0">
                            {browserState.engine === 'jina_reader' ? 'Jina' : browserState.engine === 'playwright' ? 'Browser' : 'HTTP'}
                          </span>
                        )}
                      </div>
                      <p className="text-[10px] text-muted font-mono truncate">{browserState.url}</p>
                      {screenshotUrl && (
                        <div className="rounded-lg border border-border overflow-hidden bg-white">
                          <img
                            src={screenshotUrl}
                            alt="Screenshot"
                            className="w-full h-auto"
                            onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                          />
                        </div>
                      )}
                      {browserState.contentPreview && (
                        <div className="rounded-lg bg-[var(--bg-secondary)] border border-border p-2">
                          <p className="text-[10px] text-secondary leading-relaxed line-clamp-5">{browserState.contentPreview}</p>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <div className="w-6 h-6 text-red-400 mx-auto mb-1">✕</div>
                        <p className="text-[11px] text-red-400">Failed to load page</p>
                        <p className="text-[10px] text-muted mt-0.5">{browserState.error || 'Unknown error'}</p>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ====== 文件树节点 ======

function TreeNode({ node, depth, activeFile, onOpen, onDelete }: {
  node: FileNode; depth: number; activeFile: string | null
  onOpen: (path: string) => void; onDelete: (path: string) => void
}) {
  const [expanded, setExpanded] = useState(depth < 2)
  const isActive = activeFile === node.path

  if (node.type === 'directory') {
    return (
      <div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center gap-1.5 px-3 py-1 text-xs text-secondary hover:bg-hover transition-colors text-left"
          style={{ paddingLeft: `${12 + depth * 12}px` }}>
          <span className="text-[10px] text-muted w-3 text-center">{expanded ? '▾' : '▸'}</span>
          <FolderIcon className="w-3.5 h-3.5 text-brand/60 shrink-0" />
          <span className="truncate">{node.name}</span>
        </button>
        {expanded && node.children?.map(child => (
          <TreeNode key={child.path} node={child} depth={depth + 1}
            activeFile={activeFile} onOpen={onOpen} onDelete={onDelete} />
        ))}
      </div>
    )
  }

  return (
    <div className="group relative">
      <button
        onClick={() => onOpen(node.path)}
        className={`w-full flex items-center gap-1.5 px-3 py-1 text-xs transition-colors text-left ${
          isActive
            ? 'bg-brand/8 text-primary font-medium'
            : 'text-secondary hover:bg-hover'
        }`}
        style={{ paddingLeft: `${24 + depth * 12}px` }}>
        <FileIcon ext={node.extension || ''} />
        <span className="truncate flex-1">{node.name}</span>
        {node.size && node.size > 0 && (
          <span className="text-[9px] text-muted font-mono shrink-0">
            {node.size > 1024 ? `${(node.size / 1024).toFixed(1)}k` : `${node.size}b`}
          </span>
        )}
      </button>
      <button
        onClick={(e) => { e.stopPropagation(); onDelete(node.path) }}
        className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded opacity-0 group-hover:opacity-60 hover:opacity-100 hover:text-red-500 transition-all">
        <TrashIcon className="w-3 h-3" />
      </button>
    </div>
  )
}

// ====== 文件类型图标 ======

function FileIcon({ ext }: { ext: string }) {
  const isCode = ['json', 'py', 'js', 'ts', 'yaml', 'yml'].includes(ext)
  if (isCode) return <FileCodeIcon className="w-3.5 h-3.5 text-blue-400 shrink-0" />
  return <FileTextIcon className="w-3.5 h-3.5 text-muted shrink-0" />
}
