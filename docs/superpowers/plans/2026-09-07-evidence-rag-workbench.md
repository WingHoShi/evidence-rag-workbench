# Evidence RAG Workbench 实施计划

> 本计划由用户确认。当前仅完成 Task 1；后续任务须在用户恢复工作后继续。

**目标：**在 `F:\AIproject\evidence-rag-workbench` 实现单用户本地可信知识库 Web 应用：用户上传资料后，可获得带原文引用、可拒答、可评测的 RAG 问答。

**架构：**React + TypeScript 前端由 FastAPI 提供 API 与生产静态资源；SQLite 保存元数据、任务、会话与引用快照，Qdrant 保存向量，`multilingual-e5-small` 在本地生成跨语言 Embedding。生成回答调用用户在 `.env` 中配置的 OpenAI-compatible API。

**技术栈：**Python 3.12、FastAPI、SQLite、Qdrant、Sentence Transformers、`multilingual-e5-small`、BM25、React、TypeScript、Vite、Docker Compose、pytest。

## 全局约束

- 首版仅单用户、本地运行；不登录、不联网抓取、不 OCR、不处理复杂表格或旧 `.doc`。
- 支持 Markdown、TXT、DOCX、可复制文本 PDF；单文件 ≤20MB，单知识库 ≤100MB。
- API Key 仅存 `.env`，不进入浏览器、SQLite、日志或 Git。
- 默认严格基于证据回答；无可靠证据时拒答。
- LangGraph Demo 文档不提交到 Git，仅提交来源清单、采集脚本和自编受控测试数据。
- 本地 Git 优先，不创建远程仓库、不推送代码。
- Python 依赖优先使用可信国内镜像；Embedding 从 ModelScope 的 `AI-ModelScope/multilingual-e5-small` 下载。
- Docker Desktop 当前未安装；核心功能先以原生环境完成，最后安装 Docker Desktop 并验证 Compose。

## Task 1：初始化独立项目与可回退 Git 基线

- [x] 创建 `F:\AIproject\evidence-rag-workbench`，在该目录初始化独立 Git。
- [x] 创建 `.gitignore`，忽略 `.env`、`.venv/`、`node_modules/`、`data/`、模型缓存、测试缓存、构建产物和日志。
- [x] 创建 README、产品规格和本计划文件，固化已确认的边界与架构。
- [x] 首次提交：`chore: 初始化 evidence rag workbench 项目`。

## Task 2：建立可测试的前后端骨架与本地配置

- [x] 建立 FastAPI 健康检查、pytest、React + TypeScript + Vite 与 `.env.example`。
- [x] 使用本地 Qdrant 嵌入模式进行开发，预留 Docker 服务地址。
- [x] 测试健康检查、缺失 API Key 和错误配置。
- [x] 提交：`feat: 建立前后端开发骨架`。

## Task 3：知识库、文档与任务生命周期

- [x] 用 SQLite 实现知识库、文档版本、解析任务、会话、消息与引用快照。
- [x] 实现创建/删除知识库、上传/删除/重试文档及任务状态 API。
- [x] 上传文件复制到项目数据目录，计算 Hash 防重复，不改动原文件。
- [x] 覆盖大小限制、格式校验、跨库隔离、删除同步、失败重试测试。
- [x] 提交：`feat: 实现知识库与文档生命周期`。

## Task 4：解析、切分、Embedding 与向量索引

- [x] 实现 Markdown、TXT、DOCX、PDF 解析，保留标题、页码或段落定位。
- [x] 实现结构化切分与 `multilingual-e5-small` Embedding。
- [x] 用 Qdrant 保存 384 维向量和引用 Payload，并以知识库 ID 强制过滤。
- [x] 记录模型和索引状态；模型切换时强制重建索引。
- [x] 测试解析、跨语言检索、引用定位与索引重建。
- [x] 提交：`feat: 完成文档解析与向量索引`。

> 实现说明：真实模型下载采用仅 SafeTensors 的白名单与延迟加载；本机首次下载曾因 ModelScope 传输停滞而停止，未产生完整权重。离线测试使用确定性的假 Embedding 验证索引流程，真实模型冒烟验证待模型下载完成后补做。

## Task 5：检索基线、混合检索与严格问答

- [x] 实现纯向量检索基线，再加入 BM25 与 RRF 融合。
- [x] 实现 OpenAI-compatible SSE 问答接口。
- [x] 以 `[S1]...[S5]` 注入来源，校验引用；无证据或引用异常时拒答。
- [x] 将外部文档视为不可信内容，防护提示注入。
- [x] 测试检索、RRF、拒答、无效引用、提示注入和 SSE 错误。
- [x] 提交：`feat: 实现可信混合检索问答`。

> 实现说明：为避免 SSE 已输出的无效回答无法撤回，后端先缓冲模型完整输出并完成引用校验，再依次发送 `sources`、`delta`、`done` 事件。后端测试使用假 Embedding 与假 OpenAI-compatible 流；真实模型权重与真实 API 的端到端验证仍待本地配置就绪后补做。

## Task 6：中文产品界面与可追溯体验

- [ ] 实现知识库、文档上传、任务状态、问答、引用、历史和设置页面。
- [ ] 设置页只管理非敏感模型与检索参数；API Key 通过 `.env` 配置。
- [ ] 所有界面使用中文，保留英文技术原文与引用。
- [ ] 提交：`feat: 完成知识库工作台界面`。

## Task 7：可复现 Demo 语料与人工金标评测

- [ ] 创建 LangGraph 官方核心文档来源清单与限速采集脚本。
- [ ] 创建原创、明确标记的受控评测文档与提示注入样本。
- [ ] 创建 40 条人工金标题，覆盖中英文、跨语言、跨段与拒答。
- [ ] 输出 Recall@5、引用命中、拒答正确性、检索和生成耗时。
- [ ] 对比纯向量与混合检索，不预设宣传指标。
- [ ] 提交：`feat: 增加可复现评测体系`。

## Task 8：容器化、验收与项目交付

- [ ] 安装并验证 Docker Desktop WSL 2 环境。
- [ ] 创建多阶段 Dockerfile 与只含 API、Qdrant 的 Compose 配置。
- [ ] 验证容器重启后的数据与索引恢复。
- [ ] 完整运行后端测试、前端构建、Docker 启动、上传、问答、拒答、删除和评测。
- [ ] 完善 README 与运行手册；不发布公网、不推送 GitHub。
- [ ] 最终提交：`feat: 完成交付版可信知识库工作台`。

## 验收标准

- 多知识库隔离、四种文件格式、文档生命周期和任务状态完整可用。
- 中文问题可检索英文 LangGraph 文档，并提供原文依据。
- 无依据与提示注入场景安全拒答。
- 金标评测可重复运行，保留真实结果。
- 原生环境与 Docker Compose 均能启动完整 Demo。
- Git 历史包含独立里程碑，可安全回退。
