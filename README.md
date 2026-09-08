# Evidence RAG Workbench

单用户、本地运行的可信知识库工作台。用户上传自己的资料后，系统通过本地检索与可配置的大模型 API 生成带原文依据的回答；当知识库没有可靠证据时，系统应明确拒答。

## 当前状态

已完成可测试的前后端开发骨架、文档生命周期和向量索引：FastAPI 提供 `GET /api/health`、知识库管理、文档上传与手动索引 API；React/Vite 目前仍是中文工作台占位页面。生成问答与可视化界面尚未实现。

上传文件会复制到项目 `data/uploads/`，原始文件不会被修改。上传阶段只校验文件后缀、大小、知识库容量和重复 Hash，并创建 `queued` 解析任务；随后由索引入口校验 DOCX/PDF 是否包含可提取文本、完成内容切分与向量写入。

索引入口会解析 Markdown、TXT、DOCX 和可复制文本 PDF，按标题、段落或 PDF 页码保留定位信息，再以本地 `multilingual-e5-small` 生成 384 维向量写入 Qdrant。模型默认使用 CPU、批量大小为 16；首次索引需要从 ModelScope 下载模型到已忽略的 `models/`，此过程不需要生成模型 API Key。扫描件或没有可复制文本的 PDF 会明确标记任务失败，不会伪装成已索引。

## 当前 API

- `POST` / `GET` / `DELETE` `/api/knowledge-bases`
- `POST` / `GET` / `DELETE` `/api/knowledge-bases/{knowledge_base_id}/documents`
- `POST` `/api/knowledge-bases/{knowledge_base_id}/documents/{document_id}/retry`
- `GET` `/api/knowledge-bases/{knowledge_base_id}/documents/{document_id}/tasks`
- `POST` `/api/knowledge-bases/{knowledge_base_id}/documents/{document_id}/index`
- `POST` `/api/knowledge-bases/{knowledge_base_id}/rebuild-index`
- `GET` `/api/knowledge-bases/{knowledge_base_id}/index-status`

删除文档或知识库只会删除项目数据目录下的副本，并同步清理同一知识库范围内的 Qdrant 向量。

每个 Qdrant 检索请求都会强制带上 `knowledge_base_id` 过滤条件，避免跨知识库返回资料。索引状态会记录 Embedding 模型名和向量维度；如果更换模型，系统会拒绝混合写入，必须通过“重建索引”入口重新生成该知识库的所有向量。

## 本地运行（开发期）

Python 依赖使用项目虚拟环境；建议通过清华 PyPI 镜像安装：

```powershell
D:\py\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" --index-url https://pypi.tuna.tsinghua.edu.cn/simple
Copy-Item .env.example .env
.\.venv\Scripts\uvicorn.exe evidence_rag.app:app --reload
```

另开一个终端启动前端（npm 已配置为使用 npmmirror）：

```powershell
Set-Location frontend
npm install
npm run dev
```

前端开发服务器会将 `/api` 请求代理到 `http://127.0.0.1:8000`。目前无需填写 API Key 即可访问健康检查；后续真正调用生成模型前，后端会拒绝未配置 `EVIDENCE_RAG_LLM_API_KEY` 的请求。

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest
Set-Location frontend
npm test
npm run build
```

## 已确认目标

- React + TypeScript 前端，FastAPI 后端。
- SQLite 管理知识库、文档任务、会话与引用快照；Qdrant 管理向量索引。
- 默认本地使用 `multilingual-e5-small` 进行中英文跨语言 Embedding。
- 生成回答兼容用户自备的 OpenAI-compatible API；密钥仅放在本地 `.env`。
- 首版支持 Markdown、TXT、DOCX 与可复制文本 PDF。
- 以 LangGraph 官方文档的可复现快照作为 Demo 语料；官方文档本体不提交到仓库。
- 通过人工金标评测集比较纯向量检索与 BM25 + RRF 混合检索。

## 明确不在首版范围内

多用户登录、URL 导入、OCR、复杂表格、旧版 `.doc`、Reranker、MCP、Agent 编排、百炼 Embedding、公网部署。

详细产品规格位于 [`docs/product-spec.md`](docs/product-spec.md)，实施计划位于 [`docs/superpowers/plans/2026-09-07-evidence-rag-workbench.md`](docs/superpowers/plans/2026-09-07-evidence-rag-workbench.md)。
