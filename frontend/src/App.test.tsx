import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  getModelConfig: vi.fn().mockResolvedValue({ configured: false, base_url: '', model: '', source: 'none' }),
  listKnowledgeBases: vi.fn(),
  createKnowledgeBase: vi.fn(),
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  indexDocument: vi.fn(),
  deleteDocument: vi.fn(),
  indexStatus: vi.fn(),
  listSessions: vi.fn(),
  listMessages: vi.fn(),
}))
const streamAnswerMock = vi.hoisted(() => vi.fn())

vi.mock('./api', () => ({ api: apiMock, streamAnswer: streamAnswerMock }))

import App from './App'
import type { DocumentItem } from './api'
import { readFileSync } from 'node:fs'

function configureKnowledgeBase(documents: DocumentItem[] = []) {
  apiMock.listKnowledgeBases.mockResolvedValue([{ id: 'kb-1', name: '验收知识库', document_count: 1 }])
  apiMock.listDocuments.mockResolvedValue(documents)
  apiMock.indexStatus.mockResolvedValue({ status: 'completed', embedding_model: 'fake-e5', last_indexed_at: null })
  apiMock.listSessions.mockResolvedValue([])
}

async function askQuestion() {
  fireEvent.change(await screen.findByRole('textbox', { name: '问题' }), { target: { value: '状态如何保存？' } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '提问' }))
  })
}

describe('App', () => {
  afterEach(() => vi.clearAllMocks())

  it('shows the ready index status in Chinese', async () => {
    configureKnowledgeBase()
    apiMock.indexStatus.mockResolvedValue({ status: 'ready', embedding_model: 'fake-e5', last_indexed_at: null })
    render(<App />)

    expect(await screen.findByText('已就绪')).toBeInTheDocument()
    expect(screen.queryByText('ready')).not.toBeInTheDocument()
  })

  it('keeps history titles readable before and after selecting a session', async () => {
    configureKnowledgeBase()
    apiMock.listSessions.mockResolvedValue([{ id: 'session-1', title: '状态如何保存？', message_count: 2 }])
    apiMock.listMessages.mockResolvedValue([])
    const style = document.createElement('style')
    style.textContent = readFileSync('src/styles.css', 'utf8')
    document.head.append(style)
    try {
      render(<App />)
      fireEvent.click(screen.getByRole('button', { name: '历史记录' }))
      const session = await screen.findByRole('button', { name: /状态如何保存/ })
      expect(getComputedStyle(session).color).toBe('rgb(23, 32, 51)')
      fireEvent.click(session)
      await waitFor(() => expect(session).toHaveClass('session-active'))
      expect(getComputedStyle(session).color).toBe('rgb(23, 32, 51)')
      expect(getComputedStyle(session).backgroundColor).toBe('rgb(237, 245, 255)')
    } finally {
      style.remove()
    }
  })

  it('renders the Chinese workbench navigation and document workflow', async () => {
    configureKnowledgeBase()
    render(<App />)

    expect(screen.getByRole('heading', { name: '可信知识库工作台' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '新建知识库' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '文档与索引' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '历史记录' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '设置' })).toBeInTheDocument()
    await waitFor(() => expect(apiMock.listKnowledgeBases).toHaveBeenCalledOnce())
  })

  it('renders assistant Markdown as semantic bold and code elements', async () => {
    configureKnowledgeBase()
    streamAnswerMock.mockImplementation(async (_knowledgeBaseId, _payload, onEvent) => {
      onEvent({ event: 'sources', data: { sources: [{ label: 'S1', original_filename: 'state.md', locator: null, quoted_text: 'State persistence stores checkpoints.' }] } })
      onEvent({ event: 'delta', data: { text: '根据 [S1]，`schedule` 节点只有在**学生请求手动检查（manual check）**时才会进入 `review`。' } })
      onEvent({ event: 'done', data: { citation_labels: ['S1'], session_id: 'session-1' } })
    })
    render(<App />)

    await askQuestion()

    expect(await screen.findByText('学生请求手动检查（manual check）', { selector: 'strong' })).toBeInTheDocument()
    expect(screen.getByText('schedule', { selector: 'code' })).toBeInTheDocument()
  })

  it('only displays sources cited by the completed answer', async () => {
    configureKnowledgeBase()
    streamAnswerMock.mockImplementation(async (_knowledgeBaseId, _payload, onEvent) => {
      onEvent({ event: 'sources', data: { sources: [
        { label: 'S1', original_filename: 'state.md', locator: null, quoted_text: 'State persistence stores checkpoints.' },
        { label: 'S2', original_filename: 'unrelated.md', locator: null, quoted_text: 'Unrelated text.' },
      ] } })
      onEvent({ event: 'delta', data: { text: 'State is saved as checkpoints. [S1]' } })
      onEvent({ event: 'done', data: { citation_labels: ['S1'], session_id: 'session-1' } })
    })
    render(<App />)

    await askQuestion()

    expect(await screen.findByText(/\[S1\] state\.md/)).toBeInTheDocument()
    expect(screen.queryByText(/\[S2\] unrelated\.md/)).not.toBeInTheDocument()
  })

  it('uploads every file selected in the document picker', async () => {
    configureKnowledgeBase()
    apiMock.uploadDocument.mockResolvedValue({})
    render(<App />)
    await waitFor(() => expect(apiMock.listDocuments).toHaveBeenCalledWith('kb-1'))

    const first = new File(['first'], 'first.md', { type: 'text/markdown' })
    const second = new File(['second'], 'second.md', { type: 'text/markdown' })
    await act(async () => {
      fireEvent.change(await screen.findByLabelText('上传资料（可多选）'), { target: { files: [first, second] } })
    })

    await waitFor(() => expect(apiMock.uploadDocument).toHaveBeenCalledTimes(2))
    expect(apiMock.uploadDocument).toHaveBeenNthCalledWith(1, 'kb-1', first)
    expect(apiMock.uploadDocument).toHaveBeenNthCalledWith(2, 'kb-1', second)
  })

  it('indexes only documents that are waiting or failed when indexing all', async () => {
    configureKnowledgeBase([
      { id: 'queued', original_filename: 'queued.md', size_bytes: 100, status: 'queued', task: { status: 'queued', error_message: null } },
      { id: 'failed', original_filename: 'failed.md', size_bytes: 100, status: 'failed', task: { status: 'failed', error_message: '解析失败' } },
      { id: 'completed', original_filename: 'completed.md', size_bytes: 100, status: 'completed', task: { status: 'completed', error_message: null } },
    ])
    apiMock.indexDocument.mockResolvedValue({})
    render(<App />)
    await waitFor(() => expect(apiMock.listDocuments).toHaveBeenCalledWith('kb-1'))

    await act(async () => {
      fireEvent.click(await screen.findByRole('button', { name: '全部开始索引（2）' }))
    })

    await waitFor(() => expect(apiMock.indexDocument).toHaveBeenCalledTimes(2))
    expect(apiMock.indexDocument).toHaveBeenNthCalledWith(1, 'kb-1', 'queued')
    expect(apiMock.indexDocument).toHaveBeenNthCalledWith(2, 'kb-1', 'failed')
    expect(apiMock.indexDocument).not.toHaveBeenCalledWith('kb-1', 'completed')
  })

  it('shows document-level progress while a batch index request is still running', async () => {
    configureKnowledgeBase([
      { id: 'first', original_filename: 'first.md', size_bytes: 100, status: 'queued', task: { status: 'queued', error_message: null } },
      { id: 'second', original_filename: 'second.md', size_bytes: 100, status: 'queued', task: { status: 'queued', error_message: null } },
    ])
    apiMock.indexDocument.mockImplementationOnce(() => new Promise(() => undefined))
    render(<App />)
    await waitFor(() => expect(apiMock.listDocuments).toHaveBeenCalledWith('kb-1'))

    fireEvent.click(await screen.findByRole('button', { name: '全部开始索引（2）' }))

    expect(await screen.findByText('正在索引 0 / 2（0%）')).toBeInTheDocument()
    expect(screen.getByText('当前：first.md')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: '索引进度' })).toHaveValue(0)
  })

})
