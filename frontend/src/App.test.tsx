import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

import App from './App'

describe('App', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the Chinese workbench navigation and document workflow', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    expect(screen.getByRole('heading', { name: '可信知识库工作台' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '新建知识库' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '文档与索引' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '历史记录' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '设置' })).toBeInTheDocument()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/knowledge-bases', undefined))
  })
})
