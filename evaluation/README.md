# 可复现评测材料

`langgraph_sources.json` 固定了 2026-09-10 从 LangGraph 官方 `llms.txt` 发现的 41 篇 Markdown 来源，覆盖入门、State/Node/Edge、Memory、Persistence、Streaming、Human-in-the-loop、错误处理和部署基础。它不包含官方正文。

运行 `python scripts/fetch_langgraph_docs.py` 才会以至少 1 秒间隔下载 Markdown；默认目标是已被 Git 忽略的 `data/demo/langgraph/`。脚本会写出每篇内容的下载时间、字节数和 SHA-256，供后续复现。

`controlled_docs/` 均为本项目原创、明确标记的受控材料；`gold_cases.jsonl` 是 40 条人工金标，包含中英文、跨概念、跨段、无依据和提示注入拒答场景。每条金标的 `expected_documents` 使用受控文档文件名。

真实运行应将每条记录写成 JSONL 后调用：

```powershell
.\.venv\Scripts\python.exe scripts\score_evaluation.py data\evaluation\hybrid-observations.jsonl --output data\evaluation\hybrid-report.json
```

记录必须包含 `case_id`、`retrieved_documents`、`cited_documents`、`outcome`、`retrieval_ms` 和可选 `generation_ms`。评分器输出 Recall@5、引用命中率、拒答正确性和平均耗时；不生成或伪造任何指标。

`run_controlled_evaluation.py` 会分别输出纯向量和混合检索的 `Recall@5`、平均检索耗时与观察记录；只有显式传入 `--with-generation` 并配置真实模型后，才会输出引用命中、拒答正确性与生成耗时。

本机已用真实 `multilingual-e5-small` 跑过一次受控检索对比；结果位于被 Git 忽略的 `data/evaluation/`，不作为可提交的宣传指标。真实生成 API 已配置，但为控制余额，仓库暂不附带引用命中、拒答正确性或生成耗时等未完整运行的性能报告。
