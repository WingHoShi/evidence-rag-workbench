export type KnowledgeBase = { id: string; name: string; document_count: number }

export type DocumentItem = {
  id: string
  original_filename: string
  size_bytes: number
  status: 'queued' | 'running' | 'completed' | 'failed'
  task: { status: string; error_message: string | null }
}

export type IndexStatus = { status: string; embedding_model: string; last_indexed_at: string | null }
export type Citation = { label: string; original_filename: string; locator: string | null; quoted_text: string }
export type ChatMessage = { id?: string; role: 'user' | 'assistant'; content: string; citations: Citation[] }
export type ChatSession = { id: string; title: string | null; message_count: number; updated_at: string }
type ApiError = { detail?: string }
export type ModelConfigStatus = { configured: boolean; base_url: string; model: string; source: 'file' | 'environment' | 'none' }
export type ModelConfigInput = { base_url: string; model: string; api_key?: string }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiError
    throw new Error(body.detail || `请求失败（${response.status}）`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  getModelConfig: () => request<ModelConfigStatus>('/api/model-config'),
  saveModelConfig: (payload: ModelConfigInput) => request<ModelConfigStatus>('/api/model-config', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
  testModelConfig: (payload: ModelConfigInput) => request<{ ok: boolean }>('/api/model-config/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
  listKnowledgeBases: () => request<KnowledgeBase[]>('/api/knowledge-bases'),
  createKnowledgeBase: (name: string) => request<KnowledgeBase>('/api/knowledge-bases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }),
  listDocuments: (knowledgeBaseId: string) => request<DocumentItem[]>(`/api/knowledge-bases/${knowledgeBaseId}/documents`),
  uploadDocument: (knowledgeBaseId: string, file: File) => { const body = new FormData(); body.append('file', file); return request<DocumentItem>(`/api/knowledge-bases/${knowledgeBaseId}/documents`, { method: 'POST', body }) },
  indexDocument: (knowledgeBaseId: string, documentId: string) => request<DocumentItem>(`/api/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/index`, { method: 'POST' }),
  deleteDocument: (knowledgeBaseId: string, documentId: string) => request<void>(`/api/knowledge-bases/${knowledgeBaseId}/documents/${documentId}`, { method: 'DELETE' }),
  indexStatus: (knowledgeBaseId: string) => request<IndexStatus>(`/api/knowledge-bases/${knowledgeBaseId}/index-status`),
  listSessions: (knowledgeBaseId: string) => request<ChatSession[]>(`/api/knowledge-bases/${knowledgeBaseId}/chat-sessions`),
  listMessages: (knowledgeBaseId: string, sessionId: string) => request<ChatMessage[]>(`/api/knowledge-bases/${knowledgeBaseId}/chat-sessions/${sessionId}/messages`),
}

export type StreamEvent =
  | { event: 'sources'; data: { sources: Citation[] } }
  | { event: 'delta'; data: { text: string } }
  | { event: 'done'; data: { citation_labels: string[]; session_id: string } }
  | { event: 'refusal'; data: { reason: string } }
  | { event: 'error'; data: { message: string } }

export async function streamAnswer(knowledgeBaseId: string, payload: { question: string; top_k: number; session_id?: string }, onEvent: (event: StreamEvent) => void) {
  const response = await fetch(`/api/knowledge-bases/${knowledgeBaseId}/chat/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  if (!response.ok || !response.body) {
    const body = (await response.json().catch(() => ({}))) as ApiError
    throw new Error(body.detail || '问答请求未成功建立')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split('\n\n')
    buffer = done ? '' : blocks.pop() || ''
    for (const block of blocks) {
      const event = block.match(/^event: (.+)$/m)?.[1]
      const data = block.match(/^data: (.+)$/m)?.[1]
      if (event && data) onEvent({ event, data: JSON.parse(data) } as StreamEvent)
    }
    if (done) return
  }
}
