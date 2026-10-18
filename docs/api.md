# API 与事件说明

[返回项目首页](../README.md)

以下路径相对应用服务，例如 `http://127.0.0.1:8000`。项目为单用户本地应用，知识库范围过滤不是多租户权限系统；不要把这些接口直接暴露到公共网络。运行实例的交互文档可在 `/docs` 查看。

## 模型配置（本机接口）

- `GET /api/model-config`：只返回 `configured`、`base_url`、`model` 和 `source`（`file` / `environment` / `none`），不返回密钥。
- `PUT /api/model-config`：保存 `{"base_url":"https://api.deepseek.com","model":"deepseek-flash","api_key":"你的密钥"}`；**不调用模型**，下次问答生效。首次必须填密钥；同地址可省略以沿用，更换地址必须重填。
- `POST /api/model-config/test`：同样的请求字段，发送固定短测试文本，可能计费，不保存、不自动重试；成功返回 `{"ok":true}`。成功仅说明该次短请求得到有效回复，不代表 RAG 完整链路已验收。

配置接口只允许可信本机 Host 与同源请求（另允许本机 Vite 5173 开发来源），跨站请求拒绝。地址不允许内嵌凭证、查询或片段；远程要求 HTTPS，回环服务允许 HTTP。错误不回显提交密钥或上游正文。配置状态响应禁用缓存，未提供公网或多租户鉴权。

## 健康与知识库接口

- `GET /api/health`：读取服务状态和 Qdrant 模式，不调用生成模型。
- `POST /api/knowledge-bases`：创建知识库，请求为 `{"name":"框架学习笔记"}`。
- `GET /api/knowledge-bases`：列出知识库。
- `DELETE /api/knowledge-bases/{knowledge_base_id}`：删除指定知识库的应用数据与对应向量，是破坏性操作，先确认范围与备份。

## 文档与索引

- `POST /api/knowledge-bases/{knowledge_base_id}/documents`：multipart 上传，文件字段为 `file`。
- `GET /api/knowledge-bases/{knowledge_base_id}/documents`：读取文档列表、版本状态和任务信息。
- `DELETE /api/knowledge-bases/{knowledge_base_id}/documents/{document_id}`：删除应用副本和对应向量，不修改来源文件。
- `POST /api/knowledge-bases/{knowledge_base_id}/documents/{document_id}/retry`：将失败文档重新置入可处理状态；不等于已经完成索引。
- `GET /api/knowledge-bases/{knowledge_base_id}/documents/{document_id}/tasks`：查看该文档的任务记录。
- `POST /api/knowledge-bases/{knowledge_base_id}/documents/{document_id}/index`：解析、切分、Embedding 与索引写入。
- `POST /api/knowledge-bases/{knowledge_base_id}/rebuild-index`：清理并重建当前知识库的向量索引；有修改效果，不能当作只读检查。
- `GET /api/knowledge-bases/{knowledge_base_id}/index-status`：读取模型名、维度、索引状态和时间。

上传阶段校验后缀、大小、知识库容量和重复 Hash，并创建 queued 任务；DOCX/PDF 文本提取与分块在索引阶段执行。候选查询强制按知识库过滤，更换 Embedding 模型或维度后不允许混合写入。

## 问答与 SSE

`POST /api/knowledge-bases/{knowledge_base_id}/chat/stream`

```json
{
  "question": "这份材料中如何描述状态恢复？",
  "top_k": 5
}
```

`question` 长度为 1–4000，`top_k` 为 1–5；需要在已有会话中保存时可提供该知识库下的 `session_id`。调用可能产生生成模型费用，问题与候选材料会发送给配置的服务商。

正常响应使用 `text/event-stream`，按 SSE 的空行分隔事件解析，不要假定一次网络读取就等于一个完整事件：

- `sources`：本次候选来源，含编号、文件名、定位及片段原文。
- `delta`：展示文本。
- `done`：实际引用编号、阶段耗时及保存后的会话 ID。
- `error`：模型配置、连接或协议等异常的安全提示，不把失败内容当作成功回答。

后端先缓冲完整生成内容并校验有效引用，再返回可展示内容。无可靠候选、引用缺失/越界或规则识别的不可信指令可触发拒答；拒答也是可展示的业务结果，不应只根据 HTTP 200 判断是否成功回答。实际字段结构以当前接口实现为准。

引用编号合法只说明编号在候选范围内，不能自动证明每句话均由原文支持。规则筛查也不能代替完整提示注入防护。

## 会话历史

- `GET /api/knowledge-bases/{knowledge_base_id}/chat-sessions`：列出该知识库的会话。
- `GET /api/knowledge-bases/{knowledge_base_id}/chat-sessions/{session_id}/messages`：读取问答和引用快照；会话不属于当前知识库时返回 404。

成功完成的问答会保存问题、回答和实际引用的快照。只读取历史不会重新调用生成模型；快照保留当时的原文与版本，不能据此推断当前原文件仍存在或内容未变化。
