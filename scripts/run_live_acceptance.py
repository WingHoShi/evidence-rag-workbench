"""对正在运行的本地知识库执行固定验收集，并保存真实观测结果。"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

import httpx

from evidence_rag.evaluation import evaluate, load_gold_cases
from evidence_rag.live_evaluation import observation_from_events


def read_sse_events(response: httpx.Response) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    current_event = "message"
    for line in response.iter_lines():
        if line.startswith("event: "):
            current_event = line.removeprefix("event: ")
        elif line.startswith("data: "):
            events.append((current_event, json.loads(line.removeprefix("data: "))))
    return events


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def render_summary(report: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# LangGraph 真实验收报告",
        "",
        "本报告基于本机当前知识库与本地配置的模型运行；仅代表这 10 条固定验收题，不代表通用业务性能。",
        "",
        f"- 题目数：{report['case_count']}（可回答 {report['answerable_case_count']}，应拒答 {report['case_count'] - report['answerable_case_count']}）",
        f"- Recall@5：{report['recall_at_5']:.2%}",
        f"- 引用命中率：{report['citation_hit_rate']:.2%}",
        f"- 拒答正确性：{report['refusal_accuracy']:.2%}",
        f"- 平均检索耗时：{report['average_retrieval_ms']:.2f} ms",
        f"- 平均生成耗时：{report['average_generation_ms']:.2f} ms" if report["average_generation_ms"] is not None else "- 平均生成耗时：无",
        f"- 平均总耗时：{report['average_total_ms']:.2f} ms",
        "",
        "| 题目 | 结果 | 检索 ms | 生成 ms | 总耗时 ms |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        generation = "-" if row["generation_ms"] is None else f"{row['generation_ms']:.2f}"
        lines.append(
            f"| {row['case_id']} | {row['outcome']} | {row['retrieval_ms']:.2f} | {generation} | {row['total_ms']:.2f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-base-id", required=True, help="要验收的现有知识库 UUID")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", type=Path, default=Path("evaluation/langgraph_live_acceptance_cases.jsonl"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/evaluation") / f"langgraph-live-{datetime.now().strftime('%Y-%m-%d')}",
    )
    args = parser.parse_args()
    cases = load_gold_cases(args.cases)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    observations = []
    # 本机 API 不应继承系统代理，否则 127.0.0.1 可能被代理服务错误转发。
    with httpx.Client(timeout=120, trust_env=False) as client:
        for case in cases:
            url = f"{args.base_url.rstrip('/')}/api/knowledge-bases/{args.knowledge_base_id}/chat/stream"
            with client.stream("POST", url, json={"question": case.question, "top_k": 5}) as response:
                response.raise_for_status()
                events = read_sse_events(response)
            observation, row = observation_from_events(case.id, events)
            rows.append({
                **row,
                "question": case.question,
                "expected_documents": list(case.expected_documents),
                "expect_refusal": case.expect_refusal,
            })
            observations.append(observation)
            print(f"[{len(rows)}/{len(cases)}] {case.id}: {observation.outcome}")

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "knowledge_base_id": args.knowledge_base_id,
        **evaluate(cases, observations),
        "average_total_ms": fmean(row["total_ms"] for row in rows),
    }
    write_jsonl(args.output_dir / "observations.jsonl", rows)
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "summary.md").write_text(render_summary(report, rows), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"结果已写入：{args.output_dir}")


if __name__ == "__main__":
    main()
