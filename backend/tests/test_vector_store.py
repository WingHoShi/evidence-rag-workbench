from qdrant_client import QdrantClient

from evidence_rag.settings import Settings
from evidence_rag.vector_store import create_qdrant_client


def test_local_qdrant_client_uses_configured_embedded_path(tmp_path) -> None:
    settings = Settings(qdrant_mode="local", qdrant_path=tmp_path / "qdrant")

    client = create_qdrant_client(settings)

    assert isinstance(client, QdrantClient)
    client.close()
