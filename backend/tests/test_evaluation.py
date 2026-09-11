import json

import pytest

from evidence_rag.evaluation import EvaluationObservation, GoldCase, evaluate, evaluate_retrieval, load_gold_cases


def test_evaluator_reports_recall_citation_refusal_and_latency() -> None:
    cases = [
        GoldCase("answer-hit", "What is a checkpoint?", ("persistence.md",), False),
        GoldCase("answer-miss", "What is a node?", ("graph-api.md",), False),
        GoldCase("refusal", "What is the launch code?", (), True),
    ]
    observations = [
        EvaluationObservation("answer-hit", ("persistence.md",), ("persistence.md",), "answered", 12.0, 32.0),
        EvaluationObservation("answer-miss", ("overview.md",), ("overview.md",), "answered", 18.0, 40.0),
        EvaluationObservation("refusal", (), (), "refused", 6.0, None),
    ]

    report = evaluate(cases, observations)

    assert report["case_count"] == 3
    assert report["answerable_case_count"] == 2
    assert report["recall_at_5"] == 0.5
    assert report["citation_hit_rate"] == 0.5
    assert report["refusal_accuracy"] == 1.0
    assert report["average_retrieval_ms"] == 12.0
    assert report["average_generation_ms"] == 36.0


def test_gold_loader_requires_unique_ids_and_expected_fields(tmp_path) -> None:
    path = tmp_path / "gold.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"id": "a", "question": "q", "expected_documents": ["a.md"], "expect_refusal": False}),
                json.dumps({"id": "a", "question": "q2", "expected_documents": [], "expect_refusal": True}),
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="重复"):
        load_gold_cases(path)


def test_retrieval_evaluator_excludes_refusal_cases_from_recall() -> None:
    cases = [
        GoldCase("hit", "q", ("guide.md",), False),
        GoldCase("miss", "q", ("other.md",), False),
        GoldCase("refusal", "q", (), True),
    ]
    retrieved = {"hit": ("guide.md",), "miss": ("guide.md",), "refusal": ()}

    report = evaluate_retrieval(cases, retrieved, {"hit": 10.0, "miss": 20.0, "refusal": 30.0})

    assert report == {"case_count": 3, "answerable_case_count": 2, "recall_at_5": 0.5, "average_retrieval_ms": 20.0}
