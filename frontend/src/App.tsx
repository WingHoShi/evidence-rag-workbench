import { FormEvent, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkCjkFriendly from 'remark-cjk-friendly/bidi'
import { api, ChatMessage, ChatSession, Citation, DocumentItem, IndexStatus, KnowledgeBase, streamAnswer } from './api'
import './styles.css'
import ModelSettings from './ModelSettings'

type Page = 'workbench' | 'history' | 'settings'
type IndexProgress = { completed: number; total: number; currentFilename?: string; failures: number; active: boolean }
const statusText: Record<string, string> = { queued: '等待索引', running: '正在索引', ready: '已就绪', completed: '已就绪', failed: '索引失败', not_indexed: '尚未索引' }

function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null
  return <section className="citations" aria-label="回答引用">{citations.map((citation) => <details key={`${citation.label}-${citation.original_filename}-${citation.locator}`}><summary>[{citation.label}] {citation.original_filename} · {citation.locator || '文档片段'}</summary><blockquote>{citation.quoted_text}</blockquote></details>)}</section>
}

function App() {
  const [page, setPage] = useState<Page>('workbench')
  const [modelConfigured, setModelConfigured] = useState<boolean | null>(null)
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null)
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [name, setName] = useState('')
  const [question, setQuestion] = useState('')
  const [topK, setTopK] = useState(() => Number(localStorage.getItem('evidence-rag-top-k') || 5))
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [indexProgress, setIndexProgress] = useState<IndexProgress | null>(null)
  const activeKnowledgeBase = knowledgeBases.find((item) => item.id === selectedId)

  async function refreshKnowledgeBases(preferredId?: string) {
    const items = await api.listKnowledgeBases()
    setKnowledgeBases(items)
    const nextId = preferredId || selectedId || items[0]?.id || ''
    if (items.some((item) => item.id === nextId)) setSelectedId(nextId)
  }
  async function refreshContent(knowledgeBaseId: string) {
    const [nextDocuments, nextIndex, nextSessions] = await Promise.all([api.listDocuments(knowledgeBaseId), api.indexStatus(knowledgeBaseId), api.listSessions(knowledgeBaseId)])
    setDocuments(nextDocuments); setIndexStatus(nextIndex); setSessions(nextSessions)
  }
  useEffect(() => { void refreshKnowledgeBases().catch((error: Error) => setNotice(error.message)) }, [])
  useEffect(() => { void api.getModelConfig().then(value => setModelConfigured(value.configured)).catch(() => setNotice('无法读取模型配置，请到设置页检查。')) }, [])
  useEffect(() => {
    if (!selectedId) { setDocuments([]); setIndexStatus(null); setSessions([]); setMessages([]); setIndexProgress(null); return }
    setIndexProgress(null)
    setActiveSessionId(undefined); setMessages([])
    void refreshContent(selectedId).catch((error: Error) => setNotice(error.message))
  }, [selectedId])

  async function createKnowledgeBase(event: FormEvent) {
    event.preventDefault()
    try { setBusy(true); const created = await api.createKnowledgeBase(name); setName(''); await refreshKnowledgeBases(created.id); setNotice(`已创建知识库「${created.name}」`) } catch (error) { setNotice((error as Error).message) } finally { setBusy(false) }
  }
  async function upload(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || [])
    if (!files.length || !selectedId) return
    const failures: string[] = []
    let uploaded = 0
    try {
      setBusy(true)
      for (const file of files) {
        try { await api.uploadDocument(selectedId, file); uploaded += 1 } catch (error) { failures.push(`${file.name}：${(error as Error).message}`) }
      }
      await refreshContent(selectedId); await refreshKnowledgeBases(selectedId)
      setNotice(failures.length ? `已上传 ${uploaded}/${files.length} 个文件；失败：${failures.join('；')}` : `已上传 ${uploaded} 个文件，请开始索引。`)
    } catch (error) { setNotice((error as Error).message) } finally { event.target.value = ''; setBusy(false) }
  }
  async function indexDocument(documentId: string) {
    await indexDocuments([documentId])
  }
  async function indexDocuments(documentIds: string[]) {
    if (!selectedId) return
    const failures: string[] = []
    let indexed = 0
    try {
      setBusy(true); setIndexProgress({ completed: 0, total: documentIds.length, failures: 0, active: true })
      for (const documentId of documentIds) {
        const currentFilename = documents.find((document) => document.id === documentId)?.original_filename || '文档'
        setIndexProgress({ completed: indexed, total: documentIds.length, currentFilename, failures: failures.length, active: true })
        try { await api.indexDocument(selectedId, documentId); indexed += 1 } catch (error) { failures.push((error as Error).message) }
        setIndexProgress({ completed: indexed, total: documentIds.length, currentFilename, failures: failures.length, active: true })
      }
      await refreshContent(selectedId)
      setIndexProgress({ completed: indexed, total: documentIds.length, failures: failures.length, active: false })
      setNotice(failures.length ? `已完成 ${indexed}/${documentIds.length} 个文件索引；失败：${failures.join('；')}` : documentIds.length === 1 ? '索引完成，可以开始提问。' : `已完成 ${indexed} 个文件索引，可以开始提问。`)
    } catch (error) { setNotice((error as Error).message) } finally { setIndexProgress((current) => current ? { ...current, active: false } : null); setBusy(false) }
  }
  async function removeDocument(documentId: string) {
    if (!selectedId || !window.confirm('删除只会移除项目数据目录中的副本和向量，确定继续吗？')) return
    try { setBusy(true); await api.deleteDocument(selectedId, documentId); await refreshContent(selectedId); await refreshKnowledgeBases(selectedId) } catch (error) { setNotice((error as Error).message) } finally { setBusy(false) }
  }
  async function openSession(sessionId: string) {
    if (!selectedId) return
    try { setBusy(true); setMessages(await api.listMessages(selectedId, sessionId)); setActiveSessionId(sessionId); setPage('history') } catch (error) { setNotice((error as Error).message) } finally { setBusy(false) }
  }
  async function ask(event: FormEvent) {
    event.preventDefault()
    if (!selectedId || !question.trim()) return
    const askedQuestion = question.trim(); let sources: Citation[] = []; let answer = ''
    try {
      setBusy(true); setNotice('正在检索并校验引用…')
      await streamAnswer(selectedId, { question: askedQuestion, top_k: topK, session_id: activeSessionId }, (event) => {
        if (event.event === 'sources') sources = event.data.sources
        if (event.event === 'delta') answer += event.data.text
        if (event.event === 'done') {
          const citedSources = sources.filter((source) => event.data.citation_labels.includes(source.label))
          setActiveSessionId(event.data.session_id); setMessages((current) => [...current, { role: 'user', content: askedQuestion, citations: [] }, { role: 'assistant', content: answer, citations: citedSources }]); setQuestion(''); setNotice('回答已保存到本地历史。'); void api.listSessions(selectedId).then(setSessions)
        }
        if (event.event === 'refusal') setNotice(event.data.reason)
        if (event.event === 'error') setNotice(event.data.message)
      })
    } catch (error) { setNotice((error as Error).message) } finally { setBusy(false) }
  }
  function updateTopK(value: number) { setTopK(value); localStorage.setItem('evidence-rag-top-k', String(value)) }
  const indexableDocumentIds = documents.filter((document) => document.status === 'queued' || document.status === 'failed').map((document) => document.id)
  const indexProgressText = indexProgress && (indexProgress.active ? `正在索引 ${indexProgress.completed} / ${indexProgress.total}（${Math.round(indexProgress.completed / indexProgress.total * 100)}%）` : `索引完成 ${indexProgress.completed} / ${indexProgress.total}`)

  const messageView = <div className="messages">{messages.length === 0 && <p className="empty-state">索引完成后，在这里提问。引用会保留原始技术文本。</p>}{messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.id || index}-${message.content}`}><span>{message.role === 'user' ? '你' : '助手'}</span>{message.role === 'assistant' ? <div className="message-content"><ReactMarkdown remarkPlugins={[remarkCjkFriendly]}>{message.content}</ReactMarkdown></div> : <p>{message.content}</p>}<CitationList citations={message.citations} /></article>)}</div>
  return <main className="app-shell">
    <aside className="sidebar"><div className="brand"><span>Evidence RAG</span><strong>可信知识库工作台</strong></div><nav aria-label="主导航"><button className={page === 'workbench' ? 'nav-active' : ''} onClick={() => setPage('workbench')}>工作台</button><button className={page === 'history' ? 'nav-active' : ''} onClick={() => setPage('history')}>历史记录</button><button className={page === 'settings' ? 'nav-active' : ''} onClick={() => setPage('settings')}>设置</button></nav><section className="knowledge-base-list" aria-label="知识库列表"><p className="section-label">知识库</p>{knowledgeBases.map((item) => <button className={item.id === selectedId ? 'knowledge-base-active' : ''} key={item.id} onClick={() => setSelectedId(item.id)}><span>{item.name}</span><small>{item.document_count} 个文档</small></button>)}</section></aside>
    <section className="content"><header className="topbar"><div><p className="eyebrow">本地单用户 · 证据优先</p><h1>可信知识库工作台</h1></div>{notice && <p className="notice" role="status">{notice}</p>}</header>
      {page === 'workbench' && modelConfigured === false && <div className="notice model-config-guide">尚未配置生成模型。你可以先管理文档，或<button className="text-button" onClick={() => setPage('settings')}>前往设置自己的 API</button>。</div>}
      {page === 'workbench' && <><section className="panel create-panel"><div><h2>{activeKnowledgeBase?.name || '开始创建你的知识库'}</h2><p>文档与索引保存在本机；问答时选中片段会发送给配置的模型服务。</p></div><form onSubmit={createKnowledgeBase}><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：LangGraph 学习笔记" aria-label="知识库名称"/><button disabled={busy}>新建知识库</button></form></section><div className="workspace-grid"><section className="panel documents-panel"><div className="panel-heading"><div><h2>文档与索引</h2><p>支持 Markdown、TXT、DOCX、可复制文本 PDF。</p></div><span className={`status-chip status-${indexStatus?.status || 'not_indexed'}`}>{statusText[indexStatus?.status || 'not_indexed'] || indexStatus?.status}</span></div><label className="upload-button">上传资料（可多选）<input type="file" accept=".md,.markdown,.txt,.docx,.pdf" multiple onChange={upload} disabled={!selectedId || busy}/></label>{indexableDocumentIds.length > 0 && <button onClick={() => indexDocuments(indexableDocumentIds)} disabled={busy}>全部开始索引（{indexableDocumentIds.length}）</button>}{indexProgress && <section className="index-progress" aria-live="polite"><strong>{indexProgressText}</strong>{indexProgress.currentFilename && <small>当前：{indexProgress.currentFilename}</small>}<progress aria-label="索引进度" value={indexProgress.completed} max={indexProgress.total}/>{indexProgress.failures > 0 && <small className="error-text">失败：{indexProgress.failures} 份</small>}</section>}{!selectedId ? <p className="empty-state">先创建或选择一个知识库。</p> : <ul className="document-list">{documents.map((document) => <li key={document.id}><div><strong>{document.original_filename}</strong><small>{Math.ceil(document.size_bytes / 1024)} KB · {statusText[document.status] || document.status}</small>{document.task.error_message && <small className="error-text">{document.task.error_message}</small>}</div><div className="inline-actions">{document.status !== 'completed' && <button onClick={() => indexDocument(document.id)} disabled={busy}>开始索引</button>}<button className="text-button danger" onClick={() => removeDocument(document.id)} disabled={busy}>删除</button></div></li>)}</ul>}{selectedId && documents.length === 0 && <p className="empty-state">还没有资料。上传后再手动索引。</p>}</section><section className="panel chat-panel"><div className="panel-heading"><div><h2>基于证据问答</h2><p>回答需携带可核验来源；无依据时会拒答。</p></div><span className="model-note">BM25 + RRF</span></div>{messageView}<form className="question-form" onSubmit={ask}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：State 如何保存？" aria-label="问题" disabled={!selectedId || busy}/><button disabled={!selectedId || busy || !question.trim()}>提问</button></form></section></div></>}
      {page === 'history' && <section className="panel history-panel"><div className="panel-heading"><div><h2>历史记录</h2><p>成功问答和引用快照保存在本机 SQLite。</p></div></div>{!selectedId && <p className="empty-state">请选择知识库查看历史。</p>}<div className="history-layout"><ul className="session-list">{sessions.map((session) => <li key={session.id}><button className={session.id === activeSessionId ? 'session-active' : ''} onClick={() => openSession(session.id)}><strong>{session.title || '未命名对话'}</strong><small>{session.message_count} 条消息</small></button></li>)}</ul><div className="history-messages">{activeSessionId ? messageView : <p className="empty-state">选择一条对话查看内容和引用。</p>}</div></div></section>}
      {page === 'settings' && <section className="panel settings-panel"><h2>设置</h2><ModelSettings onConfigured={() => setModelConfigured(true)} /><label>每次问答使用的来源数<select value={topK} onChange={(event) => updateTopK(Number(event.target.value))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value} 条</option>)}</select></label><dl><div><dt>Embedding</dt><dd>{indexStatus?.embedding_model || '选择知识库后显示'}</dd></div><div><dt>回答策略</dt><dd>严格依据来源；无可靠证据拒答</dd></div></dl></section>}
    </section>
  </main>
}

export default App
