from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean


@dataclass(frozen=True)
class GoldCase:
    id: str
    question: str
    expected_documents: tuple[str, ...]
    expect_refusal: bool


@dataclass(frozen=True)
class EvaluationObservation:
    case_id: str
    retrieved_documents: tuple[str, ...]
    cited_documents: tuple[str, ...]
    outcome: str
    retrieval_ms: float
    generation_ms: float | None


def load_gold_cases(path: Path) -> list[GoldCase]:
    cases: list[GoldCase] = []
    ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            case_id = raw["id"]
            question = raw["question"]
            expected_documents = raw["expected_documents"]
            expect_refusal = raw["expect_refusal"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ValueError(f"第 {line_number} 行金标格式无效") from error
        if not isinstance(case_id, str) or not case_id.strip() or not isinstance(question, str) or not question.strip():
            raise ValueError(f"第 {line_number} 行缺少有效 id 或 question")
        if case_id in ids:
            raise ValueError(f"金标 id 重复：{case_id}")
        if not isinstance(expected_documents, list) or not all(isinstance(item, str) for item in expected_documents):
            raise ValueError(f"第 {line_number} 行 expected_documents 必须为字符串数组")
        if not isinstance(expect_refusal, bool):
            raise ValueError(f"第 {line_number} 行 expect_refusal 必须为布尔值")
        if expect_refusal and expected_documents:
            raise ValueError(f"第 {line_number} 行拒答题不应标注预期文档")
        ids.add(case_id)
        cases.append(GoldCase(case_id, question, tuple(expected_documents), expect_refusal))
    if not cases:
        raise ValueError("金标文件不能为空")
    return cases


def evaluate(cases: list[GoldCase], observations: list[EvaluationObservation]) -> dict:
    by_id = {observation.case_id: observation for observation in observations}
    if set(by_id) != {case.id for case in cases}:
        raise ValueError("运行记录必须与金标一一对应")

    answerable = [case for case in cases if not case.expect_refusal]
    recall_hits = [
        bool(set(case.expected_documents) & set(by_id[case.id].retrieved_documents))
        for case in answerable
    ]
    citation_hits = [
        bool(set(case.expected_documents) & set(by_id[case.id].cited_documents))
        for case in answerable
    ]
    refusal_hits = [
        (by_id[case.id].outcome == "refused") == case.expect_refusal
        for case in cases
    ]
    retrieval_times = [by_id[case.id].retrieval_ms for case in cases]
    generation_times = [
        by_id[case.id].generation_ms
        for case in cases
        if by_id[case.id].generation_ms is not None
    ]
    return {
        "case_count": len(cases),
        "answerable_case_count": len(answerable),
        "recall_at_5": _rate(recall_hits),
        "citation_hit_rate": _rate(citation_hits),
        "refusal_accuracy": _rate(refusal_hits),
        "average_retrieval_ms": fmean(retrieval_times),
        "average_generation_ms": fmean(generation_times) if generation_times else None,
    }


def evaluate_retrieval(
    cases: list[GoldCase],
    retrieved_documents: dict[str, tuple[str, ...]],
    retrieval_ms: dict[str, float],
) -> dict:
    """对不依赖生成模型的检索阶段单独评分。"""
    expected_ids = {case.id for case in cases}
    if set(retrieved_documents) != expected_ids or set(retrieval_ms) != expected_ids:
        raise ValueError("检索记录必须与金标一一对应")

    answerable = [case for case in cases if not case.expect_refusal]
    recall_hits = [
        bool(set(case.expected_documents) & set(retrieved_documents[case.id]))
        for case in answerable
    ]
    return {
        "case_count": len(cases),
        "answerable_case_count": len(answerable),
        "recall_at_5": _rate(recall_hits),
        "average_retrieval_ms": fmean(retrieval_ms.values()),
    }


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None
