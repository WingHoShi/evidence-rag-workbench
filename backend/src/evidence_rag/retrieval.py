from __future__ import annotations

import re
from collections import defaultdict
from typing import Protocol

from rank_bm25 import BM25Okapi

from evidence_rag.indexing import DocumentIndexingService


def tokenize_for_bm25(text: str) -> list[str]:
    """以英文词与单个汉字为基础的轻量分词，避免引入额外词典依赖。"""
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text.lower())


class ChunkListingIndex(Protocol):
    def list_chunks(self, knowledge_base_id: str) -> list[dict]: ...


class HybridRetriever:
    """保留纯向量基线，并以 BM25 与 RRF 产生可解释的混合检索结果。"""

    def __init__(
        self,
        indexing_service: DocumentIndexingService,
        index: ChunkListingIndex,
        *,
        rrf_k: int = 60,
        min_vector_score: float = 0.55,
    ) -> None:
        self.indexing_service = indexing_service
        self.index = index
        self.rrf_k = rrf_k
        self.min_vector_score = min_vector_score

    def vector_search(self, knowledge_base_id: str, question: str, limit: int = 5) -> list[dict]:
        return self.indexing_service.search(knowledge_base_id, question, limit)

    def hybrid_search(self, knowledge_base_id: str, question: str, limit: int = 5) -> list[dict]:
        candidate_limit = max(limit * 4, 20)
        vector_results = self.vector_search(knowledge_base_id, question, candidate_limit)
        chunks = self.index.list_chunks(knowledge_base_id)
        if not chunks:
            return []

        bm25_scores = BM25Okapi([tokenize_for_bm25(chunk["text"]) for chunk in chunks]).get_scores(
            tokenize_for_bm25(question)
        )
        bm25_ranked = [
            (chunk, float(score))
            for chunk, score in zip(chunks, bm25_scores, strict=True)
            if score > 0
        ]
        bm25_ranked.sort(key=lambda item: item[1], reverse=True)

        candidates: dict[str, dict] = {}
        ranks: defaultdict[str, list[int]] = defaultdict(list)
        for rank, result in enumerate(vector_results, start=1):
            point_id = result["point_id"]
            candidates[point_id] = {**result, "vector_score": float(result["score"]), "bm25_score": 0.0}
            ranks[point_id].append(rank)
        for rank, (chunk, score) in enumerate(bm25_ranked[:candidate_limit], start=1):
            point_id = chunk["point_id"]
            existing = candidates.get(point_id, {})
            candidates[point_id] = {
                **chunk,
                **existing,
                "vector_score": float(existing.get("vector_score", 0.0)),
                "bm25_score": score,
            }
            ranks[point_id].append(rank)

        fused = []
        for point_id, result in candidates.items():
            rrf_score = sum(1 / (self.rrf_k + rank) for rank in ranks[point_id])
            fused.append({**result, "rrf_score": rrf_score})
        fused.sort(key=lambda result: result["rrf_score"], reverse=True)
        return fused[:limit]

    def has_reliable_evidence(self, results: list[dict]) -> bool:
        return any(
            result.get("bm25_score", 0) > 0
            or result.get("vector_score", float("-inf")) >= self.min_vector_score
            for result in results
        )
