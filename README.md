# Evidence RAG Workbench

单用户、本地运行的可信知识库工作台。用户上传自己的资料后，系统通过本地检索与可配置的大模型 API 生成带原文依据的回答；当知识库没有可靠证据时，系统应明确拒答。

## 当前状态

已完成可测试的前后端开发骨架、文档生命周期、向量索引、可信问答与中文工作台：FastAPI 提供知识库、文档、索引、SSE 问答与本地历史 API；React/Vite 提供知识库选择、上传、手动索引、带引用问答、历史和设置页面。

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
- `POST` `/api/knowledge-bases/{knowledge_base_id}/chat/stream`（请求体：`{"question": "...", "top_k": 1-5}`；响应为 SSE）
- `GET` `/api/knowledge-bases/{knowledge_base_id}/chat-sessions`
- `GET` `/api/knowledge-bases/{knowledge_base_id}/chat-sessions/{session_id}/messages`

删除文档或知识库只会删除项目数据目录下的副本，并同步清理同一知识库范围内的 Qdrant 向量。

每个 Qdrant 检索请求都会强制带上 `knowledge_base_id` 过滤条件，避免跨知识库返回资料。索引状态会记录 Embedding 模型名和向量维度；如果更换模型，系统会拒绝混合写入，必须通过“重建索引”入口重新生成该知识库的所有向量。

问答先保留纯向量检索基线，再将向量候选与本地 BM25 候选使用 RRF 融合。生成前会把最多 5 个来源标为 `[S1]` 至 `[S5]`；检索无可靠依据、来源包含疑似提示注入、模型未给出有效引用或引用越界时，接口只会返回中文拒答，不会输出模型原文。为避免流式输出后无法撤回无效回答，后端会先缓冲完整模型输出并校验引用，再通过 SSE 发送 `sources`、`delta`、`done` 事件；模型配置或网络异常发送不含敏感信息的 `error` 事件。

每个成功问答会将用户问题、回答以及实际引用的文档版本、片段定位和原文快照写入 SQLite。本地历史页按知识库隔离读取这些内容；即使后续删除原文档，已保存的引用原文快照仍可用于追溯。设置页只在浏览器本地保存非敏感的 `top_k` 参数，并明确不提供 API Key 输入框。

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

`EVIDENCE_RAG_LLM_BASE_URL`、`EVIDENCE_RAG_LLM_API_KEY` 与 `EVIDENCE_RAG_LLM_MODEL` 只在后端从 `.env` 读取；浏览器、SQLite、日志和 Git 均不会保存密钥。`EVIDENCE_RAG_RETRIEVAL_MIN_VECTOR_SCORE` 控制纯向量候选可独立作为证据的最低余弦相似度，默认 `0.55`；BM25 词项命中仍可参与混合检索。

## Docker Compose（Docker Desktop 就绪后）

本机 Docker Desktop 已迁移到 `F:\DockerDesktop`。由于此 Windows 用户配置目录与 Docker Desktop 存在设置写入兼容性问题，必须先双击运行 `F:\DockerDesktop\Start-Docker-Desktop.cmd`，不要从开始菜单直接启动 Docker Desktop。

### 启动项目

Docker Desktop 的图形界面启动完成后，在项目根目录执行。这里使用 F 盘安装目录中自带的 Compose 程序，避免依赖 C 盘的用户级 Docker 配置：

```powershell
Set-Location F:\AIproject\evidence-rag-workbench
& "F:\DockerDesktop\application\resources\bin\docker-compose.exe" start
```

浏览器访问 `http://127.0.0.1:8000`；API 健康检查为 `http://127.0.0.1:8000/api/health`。首次索引时，API 容器会将 E5 模型下载到 `model_cache` 命名卷，因此第一次索引耗时会更长。

若是首次创建容器，或者修改了 Dockerfile、依赖或 `compose.yaml`，改用以下命令重新构建并后台启动：

```powershell
Set-Location F:\AIproject\evidence-rag-workbench
& "F:\DockerDesktop\application\resources\bin\docker-compose.exe" up -d --build
```

### 停止与关闭

只停止本项目服务、保留数据和容器，执行：

```powershell
Set-Location F:\AIproject\evidence-rag-workbench
& "F:\DockerDesktop\application\resources\bin\docker-compose.exe" stop
```

查看服务状态：

```powershell
& "F:\DockerDesktop\application\resources\bin\docker-compose.exe" ps
```

如果还要彻底退出 Docker Desktop，先执行上面的 `stop`，再在 Windows 系统托盘中右键 Docker 图标并选择 **Quit Docker Desktop**。直接关闭 Docker Desktop 窗口通常只是隐藏界面，不会退出 Docker 引擎。

Docker 的程序、WSL 容器磁盘、镜像、构建缓存与命名卷均落在 `F:\DockerDesktop`；`app_data` 保存 SQLite 和上传副本，`qdrant_storage` 保存向量数据。`docker-compose.exe down` 会删除容器和网络，但保留命名卷数据；只有 `docker-compose.exe down -v` 才会删除三个命名卷及其中的本地知识库数据，执行前应先自行备份。

容器基础镜像通过 DaoCloud 的 Docker Hub 镜像加速地址拉取；Dockerfile 固定使用 CPU-only PyTorch，避免下载 CUDA 运行库并意外占用大量磁盘。

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

## 当前验证边界

后端测试使用确定性的假 Embedding 和假 OpenAI-compatible 流，已经覆盖混合检索、引用校验、拒答、提示注入隔离与 SSE 服务错误。本机已验证真实 `multilingual-e5-small` 和 OpenAI-compatible API：2026-09-11 在 40 条原创受控金标上得到 Recall@5 `1.0`、引用命中率约 `61.76%`、拒答正确性 `65%`、平均检索约 `16.75ms`、平均生成约 `2447.69ms`。原始观测与报告保存在本机忽略目录 `data/evaluation/2026-09-11-generation-merged/`；这是小规模受控语料结果，不代表真实业务或通用模型性能。

## 明确不在首版范围内

多用户登录、URL 导入、OCR、复杂表格、旧版 `.doc`、Reranker、MCP、Agent 编排、百炼 Embedding、公网部署。

详细产品规格位于 [`docs/product-spec.md`](docs/product-spec.md)，实施计划位于 [`docs/superpowers/plans/2026-09-07-evidence-rag-workbench.md`](docs/superpowers/plans/2026-09-07-evidence-rag-workbench.md)。
