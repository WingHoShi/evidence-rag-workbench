# Evidence RAG Workbench

单用户、本地运行的可信知识库工作台。用户上传自己的资料后，系统通过本地检索与可配置的大模型 API 生成带原文依据的回答；当知识库没有可靠证据时，系统应明确拒答。

## 当前状态

已完成可测试的前后端开发骨架、文档生命周期、向量索引、可信问答与中文工作台：FastAPI 提供知识库、文档、索引、SSE 问答与本地历史 API；React/Vite 提供知识库选择、上传、手动索引、带引用问答、历史和设置页面。

上传文件会复制到项目 `data/uploads/`，原始文件不会被修改。上传阶段只校验文件后缀、大小、知识库容量和重复 Hash，并创建 `queued` 解析任务；随后由索引入口校验 DOCX/PDF 是否包含可提取文本、完成内容切分与向量写入。

索引入口会解析 Markdown、TXT、DOCX 和可复制文本 PDF，按标题、段落或 PDF 页码保留定位信息，再以本地 `multilingual-e5-small` 生成 384 维向量写入 Qdrant。模型默认使用 CPU、批量大小为 16；首次索引需要从 ModelScope 下载模型到已忽略的 `models/`，此过程不需要生成模型 API Key。扫描件或没有可复制文本的 PDF 会明确标记任务失败，不会伪装成已索引。

## 技术栈与设计重点

- **前端**：React、TypeScript、Vite；知识库与文档管理、问答及引用原文展开。
- **后端**：Python 3.12+、FastAPI、Pydantic；文档生命周期、接口校验和 SSE 事件返回。
- **检索**：multilingual-e5-small、Qdrant、BM25、RRF；兼顾语义与词项匹配，并强制按知识库过滤候选。
- **存储与交付**：SQLite 保存业务状态和历史引用快照；Docker Compose 组织应用与 Qdrant，持久卷保存数据和模型缓存。

问答链路：问题向量化与关键词检索 → RRF 融合候选 → 组装带编号来源的上下文 → 调用生成模型 → 校验引用与拒答条件 → 返回结果并保存历史。RRF 不是神经 Reranker，编号合法也不等于已证明答案中的每个结论都被原文支持。

## 快速体验（Docker Compose）

前提：已安装并启动 Docker Engine / Docker Desktop，支持 `docker compose`；能访问依赖、镜像和模型下载源，并准备一个 OpenAI-compatible 模型服务。以下命令在项目根目录执行，不要求固定盘符。

```powershell
# 仅首次创建；已有 .env 不要覆盖
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

编辑本地 `.env` 中的 `EVIDENCE_RAG_LLM_BASE_URL`、`EVIDENCE_RAG_LLM_MODEL`、`EVIDENCE_RAG_LLM_API_KEY`，使用你有权限调用的模型名，不将真实密钥写入仓库。随后执行：

```powershell
docker compose up -d --build
docker compose ps
```

访问 <http://127.0.0.1:8000>；健康检查为 <http://127.0.0.1:8000/api/health>。健康检查通过不代表模型连接或完整问答已验证。首次索引会下载 E5 模型，耗时和网络、硬件有关。

最短体验：创建知识库 → 上传一份不含隐私的 Markdown/TXT 文档 → 手动索引至完成 → 提问并展开引用 → 再问一个材料中没有答案的问题，观察是否拒答。样例可使用 [`evaluation/controlled_docs/`](evaluation/controlled_docs/)，其中内容是虚构受控材料，不是产品事实。

该流程会调用你配置的生成模型，可能产生费用；先阅读下方隐私与验证边界。

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

前提：Python 3.12+、Node.js 22 和 npm。以下命令在项目根目录执行，Python 依赖使用项目虚拟环境，通过清华 PyPI 镜像安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" --index-url https://pypi.tuna.tsinghua.edu.cn/simple
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\uvicorn.exe evidence_rag.app:app --reload
```

另开一个终端启动前端（以下安装命令使用 npmmirror）：

```powershell
Set-Location frontend
npm ci --registry=https://registry.npmmirror.com
npm run dev
```

前端开发服务器会将 `/api` 请求代理到 `http://127.0.0.1:8000`。目前无需填写 API Key 即可访问健康检查；后续真正调用生成模型前，后端会拒绝未配置 `EVIDENCE_RAG_LLM_API_KEY` 的请求。

`EVIDENCE_RAG_LLM_BASE_URL`、`EVIDENCE_RAG_LLM_API_KEY` 与 `EVIDENCE_RAG_LLM_MODEL` 由后端从 `.env` 读取，前端不提供密钥输入框；`.env` 已被 Git 忽略。请勿将密钥写进源码、日志或录屏。`EVIDENCE_RAG_RETRIEVAL_MIN_VECTOR_SCORE` 控制纯向量候选可独立作为证据的最低余弦相似度，默认 `0.55`；BM25 词项命中仍可参与混合检索。

## 容器数据与日常维护

在项目根目录执行 `docker compose stop` 停止服务，`docker compose start` 恢复已有容器，`docker compose logs --tail 100 api` 查看应用日志。日志可能包含业务信息，分享前先脱敏。

`app_data` 保存 SQLite 和上传副本，`qdrant_storage` 保存向量，`model_cache` 保存 Embedding 模型。重建容器不等于清空这些卷；`docker compose down` 删除容器和网络但保留命名卷，追加 `-v` 会删除命名卷数据，不能当作普通重启命令。

仓库中的本机 Windows 启动脚本、快捷方式和演示视频不作为公开运行依赖；已有本地文件保留，迁移时请使用上面的标准 Compose 命令。基础镜像使用 DaoCloud 加速，Dockerfile 使用 CPU-only PyTorch 官方 wheel 源。镜像访问失败时先检查来源与网络，不随意替换为未知镜像。

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest
Set-Location frontend
npm test
npm run build
```

### 真实 LangGraph 验收

应用启动且已导入 LangGraph Demo 文档后，可先查看知识库 ID：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/knowledge-bases
```

再运行固定的 10 条验收题。脚本会调用当前 `.env` 配置的模型，并把问题、回答、引用、检索/生成/总耗时和汇总报告写入 Git 忽略的 `data/evaluation/`：

```powershell
.\.venv\Scripts\python.exe scripts\run_live_acceptance.py --knowledge-base-id "替换为知识库 ID"
```

2026-09-13 对本机 41 篇 LangGraph 官方文档的首次真实验收中，8 条可回答题与 2 条应拒答题均符合预期；平均检索耗时约 272ms、平均生成耗时约 10.88s、平均总耗时约 11.15s。该结果只代表这 10 条固定验收题和当时的模型服务状态，不代表通用业务性能。

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

以上为历史本机记录，原始运行结果不随仓库发布，其他环境需自行复测。代码中名为 `recall_at_5` 的指标实际按预期文档是否命中计算，更接近文档级 Hit@5；引用命中不等于逐句忠实性，拒答正确性统计全部题目的预期是否匹配。40 条受控集与 10 条官方文档验收是不同实验，不能混用分母或推广为整体回答准确率。

## 隐私与使用边界

- 本项目面向单用户本地使用，不提供公网多用户鉴权；不要直接暴露到公共网络。
- Embedding 在本地运行，但生成请求会将问题和选中的材料片段发送给配置的模型服务商。使用自己的密钥，先确认材料允许出网，演示优先使用虚构资料。
- `.env`、运行数据库、上传副本、模型缓存、日志和未审查视频不应上传到公开仓库。历史引用快照可能在删除原文后继续存在，分享前也要检查历史记录。
- 规则校验可减少无依据回答与部分提示注入风险，不承诺完整的事实核验或对所有攻击免疫。

## 明确不在首版范围内

多用户登录、URL 导入、OCR、复杂表格、旧版 `.doc`、Reranker、MCP、Agent 编排、百炼 Embedding、公网部署。

详细产品规格位于 [`docs/product-spec.md`](docs/product-spec.md)，实施计划位于 [`docs/superpowers/plans/2026-09-07-evidence-rag-workbench.md`](docs/superpowers/plans/2026-09-07-evidence-rag-workbench.md)。
