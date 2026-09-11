"""在临时数据目录运行受控语料检索评测；真实生成评测需要显式开启。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from evidence_rag.answering import GroundedAnswerService, OpenAICompatibleChatClient
from evidence_rag.evaluation import EvaluationObservation, evaluate, evaluate_retrieval, load_gold_cases
from evidence_rag.indexing import DocumentIndexingService, MultilingualE5EmbeddingEngine, QdrantChunkIndex
from evidence_rag.lifecycle import DocumentLifecycleService
from evidence_rag.retrieval import HybridRetriever
from evidence_rag.settings import Settings


ROOT = Path(__file__).resolve().parents[1]


async def collect_events(answer_service: GroundedAnswerService, knowledge_base_id: str, question: str) -> list[tuple[str, dict]]:
    return [event async for event in answer_service.stream_events(knowledge_base_id, question)]


def build_services(work_dir: Path):
    settings = Settings(
        data_dir=work_dir / "data",
        qdrant_path=work_dir / "qdrant",
        embedding_model_dir=ROOT / "models" / "multilingual-e5-small",
    )
    index = QdrantChunkIndex(settings, collection_name="controlled_evaluation")
    lifecycle = DocumentLifecycleService(settings, index)
    embeddings = MultilingualE5EmbeddingEngine(settings)
    indexing = DocumentIndexingService(lifecycle, index, embeddings)
    retriever = HybridRetriever(indexing, index, min_vector_score=settings.retrieval_min_vector_score)
    knowledge_base = lifecycle.create_knowledge_base("受控评测语料")
    for source in sorted((ROOT / "evaluation" / "controlled_docs").glob("*.md")):
        relative_path = Path("fixtures") / source.name
        target = settings.data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        document = lifecycle.database.create_document(
            knowledge_base_id=knowledge_base["id"],
            original_filename=source.name,
            storage_path=relative_path.as_posix(),
            sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            size_bytes=source.stat().st_size,
        )
        indexing.index_document(knowledge_base["id"], document["id"])
    return settings, knowledge_base["id"], retriever


@contextmanager
def evaluation_workspace():
    """在删除 Windows 临时目录前释放嵌入式 Qdrant 的 SQLite 文件句柄。"""
    with tempfile.TemporaryDirectory(prefix="evidence-rag-eval-") as temporary:
        settings, knowledge_base_id, retriever = build_services(Path(temporary))
        try:
            yield settings, knowledge_base_id, retriever
        finally:
            retriever.index.close()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("data/evaluation"))
    parser.add_argument("--with-generation", action="store_true", help="调用 .env 配置的真实 OpenAI-compatible API")
    args = parser.parse_args()
    cases = load_gold_cases(ROOT / "evaluation" / "gold_cases.jsonl")
    with evaluation_workspace() as (settings, knowledge_base_id, retriever):
        vector_rows: list[dict] = []
        hybrid_rows: list[dict] = []
        answer_service = GroundedAnswerService(retriever, OpenAICompatibleChatClient(settings)) if args.with_generation else None
        for case in cases:
            start = time.perf_counter()
            vector = retriever.vector_search(knowledge_base_id, case.question, 5)
            vector_ms = (time.perf_counter() - start) * 1000
            start = time.perf_counter()
            hybrid = retriever.hybrid_search(knowledge_base_id, case.question, 5)
            hybrid_ms = (time.perf_counter() - start) * 1000
            vector_rows.append({"case_id": case.id, "retrieved_documents": [item["original_filename"] for item in vector], "retrieval_ms": vector_ms})
            row = {"case_id": case.id, "retrieved_documents": [item["original_filename"] for item in hybrid], "retrieval_ms": hybrid_ms}
            if answer_service:
                generation_start = time.perf_counter()
                events = asyncio.run(collect_events(answer_service, knowledge_base_id, case.question))
                row["generation_ms"] = (time.perf_counter() - generation_start) * 1000
                row["outcome"] = "refused" if events and events[0][0] == "refusal" else "answered"
                sources = next((event[1]["sources"] for event in events if event[0] == "sources"), [])
                row["cited_documents"] = [source["original_filename"] for source in sources]
            hybrid_rows.append(row)
        write_jsonl(args.output_dir / "vector-observations.jsonl", vector_rows)
        write_jsonl(args.output_dir / "hybrid-observations.jsonl", hybrid_rows)
        vector_report = evaluate_retrieval(
            cases,
            {row["case_id"]: tuple(row["retrieved_documents"]) for row in vector_rows},
            {row["case_id"]: row["retrieval_ms"] for row in vector_rows},
        )
        hybrid_retrieval_report = evaluate_retrieval(
            cases,
            {row["case_id"]: tuple(row["retrieved_documents"]) for row in hybrid_rows},
            {row["case_id"]: row["retrieval_ms"] for row in hybrid_rows},
        )
        (args.output_dir / "vector-retrieval-report.json").write_text(
            json.dumps(vector_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (args.output_dir / "hybrid-retrieval-report.json").write_text(
            json.dumps(hybrid_retrieval_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if answer_service:
            observations = [EvaluationObservation(
                case_id=row["case_id"], retrieved_documents=tuple(row["retrieved_documents"]), cited_documents=tuple(row["cited_documents"]), outcome=row["outcome"], retrieval_ms=row["retrieval_ms"], generation_ms=row["generation_ms"]
            ) for row in hybrid_rows]
            report = evaluate(cases, observations)
            (args.output_dir / "hybrid-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"vector": vector_report, "hybrid": hybrid_retrieval_report}, ensure_ascii=False, indent=2))
            print("未启用真实生成模型，未生成引用/拒答/生成耗时指标。")


if __name__ == "__main__":
    main()
