# Evidence RAG Workbench

单用户、本地运行的可信知识库工作台。用户上传自己的资料后，系统通过本地检索与可配置的大模型 API 生成带原文依据的回答；当知识库没有可靠证据时，系统应明确拒答。

## 当前状态

已完成可测试的前后端开发骨架：FastAPI 提供 `GET /api/health`，React/Vite 提供中文工作台占位页面。知识库、上传、检索与问答尚未实现。

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
