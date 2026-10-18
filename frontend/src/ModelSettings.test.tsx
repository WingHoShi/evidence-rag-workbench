import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import ModelSettings from './ModelSettings'

const secret = 'test-browser-private-secret'
let calls: { url: string; method: string; body?: Record<string, string> }[] = []
const status = { configured: false, base_url: '', model: '', source: 'none' }

function mockServer(config = status, failure = false) {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method || 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ url, method, body })
    if (method === 'GET') return new Response(JSON.stringify(config))
    if (failure) return new Response(JSON.stringify({ detail: '配置格式无效' }), { status: 422 })
    if (url.endsWith('/test')) return new Response(JSON.stringify({ ok: true }))
    return new Response(JSON.stringify({ configured: true, base_url: body.base_url, model: body.model, source: 'file' }))
  }))
}

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear() })

it('prefills DeepSeek without testing automatically, saves then clears the password', async () => {
  mockServer()
  render(<ModelSettings />)
  const key = await screen.findByLabelText('API Key')
  await waitFor(() => expect(screen.getByLabelText('接口地址')).toHaveValue('https://api.deepseek.com'))
  expect(screen.getByLabelText('模型名称')).toHaveValue('deepseek-flash')
  expect(key).toHaveAttribute('type', 'password')
  expect(calls).toHaveLength(1)
  fireEvent.change(key, { target: { value: secret } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  await screen.findByText(/已保存，下一次问答生效/)
  expect(key).toHaveValue('')
  expect(calls.filter(c => c.method === 'PUT')[0].body?.api_key).toBe(secret)
  expect(calls.some(c => c.url.endsWith('/test'))).toBe(false)
  expect(document.body.textContent).not.toContain(secret)
  expect(JSON.stringify(localStorage)).not.toContain(secret)
  expect(JSON.stringify(sessionStorage)).not.toContain(secret)
})

it('tests only on click with a fee warning and does not save', async () => {
  mockServer()
  render(<ModelSettings />)
  const key = await screen.findByLabelText('API Key')
  expect(await screen.findByText(/可能产生 API 费用/)).toBeInTheDocument()
  fireEvent.change(key, { target: { value: secret } })
  fireEvent.click(screen.getByRole('button', { name: '测试连接（可能计费）' }))
  await screen.findByText(/连接成功，此次测试未保存配置/)
  expect(calls.filter(c => c.method === 'POST')).toHaveLength(1)
  expect(calls.some(c => c.method === 'PUT')).toBe(false)
})

it('allows a blank key on same endpoint but requires one when changing endpoint', async () => {
  mockServer({ configured: true, base_url: 'https://old.example', model: 'old-model', source: 'environment' })
  render(<ModelSettings />)
  const input = await screen.findByLabelText('接口地址')
  await waitFor(() => expect(input).toHaveValue('https://old.example'))
  expect(screen.getByLabelText('API Key')).toHaveValue('')
  fireEvent.change(input, { target: { value: 'https://other.example' } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  await screen.findByText(/更换接口地址时必须重新输入 API Key/)
  expect(calls.some(c => c.method === 'PUT')).toBe(false)
})

it('shows safe errors and retains input after a failed save', async () => {
  mockServer(status, true)
  render(<ModelSettings />)
  const key = await screen.findByLabelText('API Key')
  fireEvent.change(key, { target: { value: secret } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  expect(await screen.findByText('配置格式无效')).toBeInTheDocument()
  expect(key).toHaveValue(secret)
  expect(document.body.textContent).not.toContain(secret)
})
