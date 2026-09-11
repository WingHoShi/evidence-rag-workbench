"""对真实运行记录评分；本脚本不生成回答，也不预置任何指标。"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from evidence_rag.evaluation import EvaluationObservation, evaluate, load_gold_cases


def load_observations(path: Path) -> list[EvaluationObservation]:
    observations = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        observations.append(EvaluationObservation(
            case_id=item["case_id"],
            retrieved_documents=tuple(item["retrieved_documents"]),
            cited_documents=tuple(item["cited_documents"]),
            outcome=item["outcome"],
            retrieval_ms=float(item["retrieval_ms"]),
            generation_ms=float(item["generation_ms"]) if item.get("generation_ms") is not None else None,
        ))
    return observations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("observations", type=Path, help="真实运行生成的 JSONL 记录")
    parser.add_argument("--gold", type=Path, default=Path("evaluation/gold_cases.jsonl"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {"generated_at": datetime.now(UTC).isoformat(), **evaluate(load_gold_cases(args.gold), load_observations(args.observations))}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
