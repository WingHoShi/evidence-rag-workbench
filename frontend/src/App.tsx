import { FormEvent, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkCjkFriendly from 'remark-cjk-friendly/bidi'
import { api, ChatMessage, ChatSession, Citation, DocumentItem, IndexStatus, KnowledgeBase, streamAnswer } from './api'
import './styles.css'

type Page = 'workbench' | 'history' | 'settings'
const statusText: Record<string, string> = { queued: '等待索引', running: '正在索引', completed: '已就绪', failed: '索引失败', not_indexed: '尚未索引' }

function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null
  return <section className="citations" aria-label="回答引用">{citations.map((citation) => <details key={`${citation.label}-${citation.original_filename}-${citation.locator}`}><summary>[{citation.label}] {citation.original_filename} · {citation.locator || '文档片段'}</summary><blockquote>{citation.quoted_text}</blockquote></details>)}</section>
}

function App() {
  const [page, setPage] = useState<Page>('workbench')
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
  useEffect(() => {
    if (!selectedId) { setDocuments([]); setIndexStatus(null); setSessions([]); setMessages([]); return }
    setActiveSessionId(undefined); setMessages([])
    void refreshContent(selectedId).catch((error: Error) => setNotice(error.message))
  }, [selectedId])

  async function createKnowledgeBase(event: FormEvent) {
    event.preventDefault()
    try { setBusy(true); const created = await api.createKnowledgeBase(name); setName(''); await refreshKnowledgeBases(created.id); setNotice(`已创建知识库「${created.name}」`) } catch (error) { setNotice((error as Error).message) } finally { setBusy(false) }
  }
  async function upload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file || !selectedId) return
    try { setBusy(true); await api.uploadDocument(selectedId, file); await refreshContent(selectedId); await refreshKnowledgeBases(selectedId); setNotice(`已上传 ${file.name}，请点击“开始索引”`) } catch (error) { setNotice((error as Error).message) } finally { event.target.value = ''; setBusy(false) }
  }
  async function indexDocument(documentId: string) {
    if (!selectedId) return
    try { setBusy(true); await api.indexDocument(selectedId, documentId); await refreshContent(selectedId); setNotice('索引完成，可以开始提问。') } catch (error) { setNotice((error as Error).message) } finally { setBusy(false) }
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

  const messageView = <div className="messages">{messages.length === 0 && <p className="empty-state">索引完成后，在这里提问。引用会保留原始技术文本。</p>}{messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.id || index}-${message.content}`}><span>{message.role === 'user' ? '你' : '助手'}</span>{message.role === 'assistant' ? <div className="message-content"><ReactMarkdown remarkPlugins={[remarkCjkFriendly]}>{message.content}</ReactMarkdown></div> : <p>{message.content}</p>}<CitationList citations={message.citations} /></article>)}</div>
  return <main className="app-shell">
    <aside className="sidebar"><div className="brand"><span>Evidence RAG</span><strong>可信知识库工作台</strong></div><nav aria-label="主导航"><button className={page === 'workbench' ? 'nav-active' : ''} onClick={() => setPage('workbench')}>工作台</button><button className={page === 'history' ? 'nav-active' : ''} onClick={() => setPage('history')}>历史记录</button><button className={page === 'settings' ? 'nav-active' : ''} onClick={() => setPage('settings')}>设置</button></nav><section className="knowledge-base-list" aria-label="知识库列表"><p className="section-label">知识库</p>{knowledgeBases.map((item) => <button className={item.id === selectedId ? 'knowledge-base-active' : ''} key={item.id} onClick={() => setSelectedId(item.id)}><span>{item.name}</span><small>{item.document_count} 个文档</small></button>)}</section></aside>
    <section className="content"><header className="topbar"><div><p className="eyebrow">本地单用户 · 证据优先</p><h1>可信知识库工作台</h1></div>{notice && <p className="notice" role="status">{notice}</p>}</header>
      {page === 'workbench' && <><section className="panel create-panel"><div><h2>{activeKnowledgeBase?.name || '开始创建你的知识库'}</h2><p>资料留在本机；API Key 只从后端 `.env` 读取。</p></div><form onSubmit={createKnowledgeBase}><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：LangGraph 学习笔记" aria-label="知识库名称"/><button disabled={busy}>新建知识库</button></form></section><div className="workspace-grid"><section className="panel documents-panel"><div className="panel-heading"><div><h2>文档与索引</h2><p>支持 Markdown、TXT、DOCX、可复制文本 PDF。</p></div><span className={`status-chip status-${indexStatus?.status || 'not_indexed'}`}>{statusText[indexStatus?.status || 'not_indexed'] || indexStatus?.status}</span></div><label className="upload-button">上传资料<input type="file" accept=".md,.markdown,.txt,.docx,.pdf" onChange={upload} disabled={!selectedId || busy}/></label>{!selectedId ? <p className="empty-state">先创建或选择一个知识库。</p> : <ul className="document-list">{documents.map((document) => <li key={document.id}><div><strong>{document.original_filename}</strong><small>{Math.ceil(document.size_bytes / 1024)} KB · {statusText[document.status] || document.status}</small>{document.task.error_message && <small className="error-text">{document.task.error_message}</small>}</div><div className="inline-actions">{document.status !== 'completed' && <button onClick={() => indexDocument(document.id)} disabled={busy}>开始索引</button>}<button className="text-button danger" onClick={() => removeDocument(document.id)} disabled={busy}>删除</button></div></li>)}</ul>}{selectedId && documents.length === 0 && <p className="empty-state">还没有资料。上传后再手动索引。</p>}</section><section className="panel chat-panel"><div className="panel-heading"><div><h2>基于证据问答</h2><p>回答需携带可核验来源；无依据时会拒答。</p></div><span className="model-note">BM25 + RRF</span></div>{messageView}<form className="question-form" onSubmit={ask}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：State 如何保存？" aria-label="问题" disabled={!selectedId || busy}/><button disabled={!selectedId || busy || !question.trim()}>提问</button></form></section></div></>}
      {page === 'history' && <section className="panel history-panel"><div className="panel-heading"><div><h2>历史记录</h2><p>成功问答和引用快照保存在本机 SQLite。</p></div></div>{!selectedId && <p className="empty-state">请选择知识库查看历史。</p>}<div className="history-layout"><ul className="session-list">{sessions.map((session) => <li key={session.id}><button className={session.id === activeSessionId ? 'session-active' : ''} onClick={() => openSession(session.id)}><strong>{session.title || '未命名对话'}</strong><small>{session.message_count} 条消息</small></button></li>)}</ul><div className="history-messages">{activeSessionId ? messageView : <p className="empty-state">选择一条对话查看内容和引用。</p>}</div></div></section>}
      {page === 'settings' && <section className="panel settings-panel"><h2>设置</h2><p>此页面不处理密钥。`Base URL`、模型名和 API Key 只从后端 `.env` 读取，避免密钥进入浏览器、本地数据库或 Git。</p><label>每次问答使用的来源数<select value={topK} onChange={(event) => updateTopK(Number(event.target.value))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value} 条</option>)}</select></label><dl><div><dt>Embedding</dt><dd>{indexStatus?.embedding_model || '选择知识库后显示'}</dd></div><div><dt>回答策略</dt><dd>严格依据来源；无可靠证据拒答</dd></div></dl></section>}
    </section>
  </main>
}

export default App
