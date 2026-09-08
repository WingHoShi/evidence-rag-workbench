from qdrant_client import QdrantClient

from evidence_rag.settings import Settings


def create_qdrant_client(settings: Settings) -> QdrantClient:
    """按配置创建开发期嵌入式或部署期服务端 Qdrant 客户端。"""
    if settings.qdrant_mode == "server":
        return QdrantClient(url=settings.qdrant_url)
    return QdrantClient(path=str(settings.qdrant_path))
