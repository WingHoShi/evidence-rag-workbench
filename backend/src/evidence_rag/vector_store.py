from typing import Protocol

from qdrant_client import QdrantClient

from evidence_rag.settings import Settings


class VectorIndex(Protocol):
    """文档生命周期需要的最小向量索引清理接口。"""

    def delete_document_vectors(self, knowledge_base_id: str, version_id: str) -> None: ...

    def delete_knowledge_base_vectors(self, knowledge_base_id: str) -> None: ...


class NoopVectorIndex:
    """索引尚未在 Task 4 建立前的安全空实现。"""

    def delete_document_vectors(self, knowledge_base_id: str, version_id: str) -> None:
        return None

    def delete_knowledge_base_vectors(self, knowledge_base_id: str) -> None:
        return None


def create_qdrant_client(settings: Settings) -> QdrantClient:
    """按配置创建开发期嵌入式或部署期服务端 Qdrant 客户端。"""
    if settings.qdrant_mode == "server":
        return QdrantClient(url=settings.qdrant_url)
    return QdrantClient(path=str(settings.qdrant_path))
