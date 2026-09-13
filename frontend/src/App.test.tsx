import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
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

function configureKnowledgeBase() {
  apiMock.listKnowledgeBases.mockResolvedValue([{ id: 'kb-1', name: '验收知识库', document_count: 1 }])
  apiMock.listDocuments.mockResolvedValue([])
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
})
