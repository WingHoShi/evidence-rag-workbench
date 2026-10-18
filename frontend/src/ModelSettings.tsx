import { FormEvent, useEffect, useState } from 'react'
import { api, ModelConfigStatus } from './api'

export default function ModelSettings({ onConfigured }: { onConfigured?: () => void }) {
  const [status, setStatus] = useState<ModelConfigStatus | null>(null)
  const [baseUrl, setBaseUrl] = useState('https://api.deepseek.com')
  const [model, setModel] = useState('deepseek-flash')
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let active = true
    api.getModelConfig().then((value) => {
      if (!active) return
      setStatus(value)
      if (value.base_url) setBaseUrl(value.base_url)
      if (value.model) setModel(value.model)
    }).catch(() => { if (active) setNotice('无法读取本机配置状态，请检查后端服务或配置文件。') })
      .finally(() => { if (active) setLoaded(true) })
    return () => { active = false }
  }, [])

  async function submit(test: boolean) {
    const normalizedUrl = baseUrl.replace(/\/+$/, '')
    if (status?.configured && !apiKey.trim() && normalizedUrl !== status.base_url) {
      setNotice('更换接口地址时必须重新输入 API Key。'); return
    }
    if (!baseUrl || !model.trim() || (!status?.configured && !apiKey.trim())) {
      setNotice('请填写接口地址、模型名称和自己的 API Key。'); return
    }
    try {
      setBusy(true); setNotice('')
      const payload = { base_url: baseUrl, model: model.trim(), api_key: apiKey || undefined }
      if (test) {
        await api.testModelConfig(payload)
        setNotice('连接成功，此次测试未保存配置。')
      } else {
        const saved = await api.saveModelConfig(payload)
        setStatus(saved); setBaseUrl(saved.base_url); setModel(saved.model); setApiKey('')
        setNotice('已保存，下一次问答生效，无需重启服务。'); onConfigured?.()
      }
    } catch (error) {
      // Even an unexpectedly unsafe server message must not echo the entered key.
      const message = error instanceof Error ? error.message : '操作失败，请重试。'
      setNotice(apiKey ? message.split(apiKey).join('[已隐藏]') : message)
    } finally { setBusy(false) }
  }

  function save(event: FormEvent) { event.preventDefault(); void submit(false) }

  return <section className="model-settings" aria-labelledby="model-settings-title">
    <h3 id="model-settings-title">生成模型 · 自备 API</h3>
    <p>优先兼容 DeepSeek。使用自己的 API Key 和额度；网页订阅或其他 Coding Plan 不一定支持此接口。</p>
    <p>{status?.configured ? `已配置 · ${status.source === 'file' ? '网页本机配置' : '环境配置'}（不回显密钥）` : '尚未配置模型，也可以先管理文档。'}</p>
    <form onSubmit={save} autoComplete="off">
      <fieldset disabled={busy || !loaded}>
        <label>接口地址<input aria-label="接口地址" type="url" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} required /></label>
        <label>模型名称<input aria-label="模型名称" value={model} onChange={e => setModel(e.target.value)} maxLength={200} required /></label>
        <label>API Key<input aria-label="API Key" type="password" autoComplete="new-password" value={apiKey} onChange={e => setApiKey(e.target.value)} maxLength={4096} placeholder={status?.configured ? '留空沿用已保存密钥' : '填写你自己的密钥'} /></label>
        <small>密钥仅保存到后端本机配置文件，不写入浏览器存储。更换接口地址需重新输入密钥。</small>
        <div className="inline-actions"><button type="submit">保存配置</button><button type="button" onClick={() => void submit(true)}>测试连接（可能计费）</button></div>
      </fieldset>
    </form>
    <p>保存配置不调用模型；主动测试连接及实际问答可能产生 API 费用。问答时问题和选中片段会发送给模型服务商。</p>
    {notice && <p role="status" className="notice">{notice}</p>}
  </section>
}
