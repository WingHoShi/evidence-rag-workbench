# 评测与验证说明

[返回项目首页](../README.md)

本页区分代码测试、历史本机观测和当前真实模型验收，不把不同范围的结果拼成整体准确率。

## 本轮配置与快捷启动回归

2026-10-18，快捷启动与模型配置功能回归：后端 **93 项**、前端 **10 项**测试通过，TypeScript 检查及前端生产构建通过。新增覆盖模型配置持久化、环境回退、请求快照、地址切换密钥保护、跨站拒绝、错误脱敏，以及网页保存/主动连接测试交互。真实模型 HTTP 调用使用 MockTransport，不消耗 API 额度。

Windows PowerShell 5.1 启动契约测试另行运行，模拟 Docker 和应用边界；不等同干净电脑安装、真实镜像构建或完整 Docker 启动验收。本轮未运行真实 DeepSeek 请求。旧脚本加载测试曾误触其 Docker Desktop 启动分支，已立即中断，未执行到 Compose 启动；新脚本已隔离加载与执行入口。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/tests/start-project.Tests.ps1
```

下面的 46 / 6 是改动前隔离副本基线，不是本轮新增功能测试数量。

## 自动化检查

2026-10-18，以提交 `7456502` 导出的隔离代码副本、已有本地依赖运行：

- 后端 46 项测试通过，包含文档生命周期、索引、检索、引用、拒答、评测解析和接口行为。
- 前端 6 项测试通过，覆盖部分工作台交互与渲染。
- TypeScript 检查及 Vite 生产构建通过。

后端用确定性假 Embedding/模型流与临时数据，前端使用测试环境。以上不等于干净机器安装、真实模型输出质量、完整浏览器流程或压力测试已经通过。记录中的 Starlette/AnyIO 弃用警告未在文档改版中处理。

复跑测试（先完成开发依赖安装）：

```powershell
.\.venv\Scripts\python.exe -m pytest
npm --prefix frontend test
npm --prefix frontend run build
```

## 两组独立评测材料

### 原创受控集：40 条

[`controlled_docs`](../evaluation/controlled_docs/) 为明确标记的虚构材料，[`gold_cases.jsonl`](../evaluation/gold_cases.jsonl) 包含中英文、跨段、无依据与材料指令等场景，可用于比较纯向量检索和 BM25 + RRF。

2026-09-11 的历史本机记录：文档命中指标 `1.0`、引用命中率约 `61.76%`、拒答正确性 `65%`，平均检索约 `16.75 ms`、平均生成约 `2447.69 ms`。原始观测位于本机忽略目录 `data/evaluation/2026-09-11-generation-merged/`，不随公共仓库分发；当前环境需要自行复测。

### LangGraph 文档验收集：10 条

[`langgraph_sources.json`](../evaluation/langgraph_sources.json) 固定了 41 篇官方 Markdown 来源清单，仓库不分发官方正文。[`langgraph_live_acceptance_cases.jsonl`](../evaluation/langgraph_live_acceptance_cases.jsonl) 包含 8 条可答题和 2 条应拒答题。

2026-09-13 的历史本机记录：这 10 条均符合预期；平均检索约 `272 ms`、生成约 `10.88 s`、端到端约 `11.15 s`。只代表该题集、材料、模型服务与环境，不代表所有回答正确率为 100%，也不能与上面的 40 题实验混用分母。

## 指标怎样解释

- **文档命中**：当前代码命名为 `recall_at_5`，按每道可答题是否命中至少一个预期文档计算，更接近文档级 Hit@5，不是对全部相关 Chunk 计算的标准 Recall。
- **引用命中**：回答实际引用中是否出现预期文档；不是逐句忠实性或结论事实正确性的完整检查。
- **拒答正确性**：所有题中，实际拒答/作答是否与预期一致，分母不只是应拒答题；既要检查无依据硬答，也要检查错误拒答。
- **耗时**：检索、生成与端到端有不同计时边界；平均值不等于 P95，也不是每次请求的延迟保证。使用脚本时应查看对应计时点。

当前完整真实模型/浏览器新一轮验收尚未完成。健康与页面资源检查不能替代上传、索引、真实回答及引用恢复等完整业务检查；本次文档改版没有重新调用真实模型。

## 复现入口

先完成 [环境安装](setup.md)。以下命令仅供手动执行，本文改版本身没有运行付费评测或下载模型。

**受控检索对比**：

```powershell
.\.venv\Scripts\python.exe scripts/run_controlled_evaluation.py
```

会使用真实本地 Embedding，首次可能下载模型，在临时工作空间建立评测索引，并将观测写入 `data/evaluation/`。默认不调用生成模型。

该脚本的旧 `--with-generation` 分支仍按已不适用的 `refusal` 事件判断拒答，并把全部候选来源计为引用；当前问答服务通过 `sources/delta/done` 返回拒答，实际引用需要按 `done.citation_labels` 筛选。因此，这个分支的引用与拒答统计不能直接作为正式质量结果。本页仅推荐其默认检索对比用法；生成验收使用下方 `run_live_acceptance.py`，并检查原始观测。这里记录问题，没有修改脚本或重跑历史实验。

**官方来源文档与真实验收**：

```powershell
# 下载来源清单中的正文，仅保存在本地忽略目录
.\.venv\Scripts\python.exe scripts/fetch_langgraph_docs.py
```

通过界面把下载的 Markdown 导入一个独立知识库并完成索引，再查看知识库 ID：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/knowledge-bases
```

确认模型费用、数据范围和生成配置后再运行：

```powershell
.\.venv\Scripts\python.exe scripts/run_live_acceptance.py --knowledge-base-id "替换为知识库ID"
```

该脚本访问运行中的服务，会调用真实模型，并保存问答历史与观测文件，不是只读测试。默认结果位于 `data/evaluation/langgraph-live-日期/`；问题、回答、原文片段和使用数据可能敏感，分享前先脱敏。

**已有观测评分**：

```powershell
.\.venv\Scripts\python.exe scripts/score_evaluation.py data/evaluation/hybrid-observations.jsonl --output data/evaluation/hybrid-report.json
```

评分只依据输入观测，不补造缺失结果。字段说明及来源信息见 [评测材料说明](../evaluation/README.md)。
