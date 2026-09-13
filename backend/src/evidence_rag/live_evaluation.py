"""把本地 SSE 问答结果转为可评分的真实验收观测记录。"""

from __future__ import annotations

from typing import Any

from evidence_rag.evaluation import EvaluationObservation


def observation_from_events(
    case_id: str,
    events: list[tuple[str, dict[str, Any]]],
) -> tuple[EvaluationObservation, dict[str, Any]]:
    """解析一条完整 SSE 响应；不读取配置，也不接触模型凭据。"""
    sources = next((data["sources"] for event, data in events if event == "sources"), [])
    answer = "".join(data["text"] for event, data in events if event == "delta")
    done = next((data for event, data in events if event == "done"), None)
    if done is None:
        raise ValueError(f"验收题 {case_id} 未收到 done 事件")

    citation_labels = done["citation_labels"]
    cited_sources = [source for source in sources if source["label"] in citation_labels]
    retrieved_documents = tuple(source["original_filename"] for source in sources)
    cited_documents = tuple(source["original_filename"] for source in cited_sources)
    generation_ms = done["generation_ms"]
    observation = EvaluationObservation(
        case_id=case_id,
        retrieved_documents=retrieved_documents,
        cited_documents=cited_documents,
        outcome="answered" if citation_labels else "refused",
        retrieval_ms=float(done["retrieval_ms"]),
        generation_ms=float(generation_ms) if generation_ms is not None else None,
    )
    return observation, {
        "case_id": case_id,
        "outcome": observation.outcome,
        "answer": answer,
        "retrieved_documents": list(retrieved_documents),
        "cited_documents": list(cited_documents),
        "retrieval_ms": observation.retrieval_ms,
        "generation_ms": observation.generation_ms,
        "total_ms": float(done["total_ms"]),
    }
