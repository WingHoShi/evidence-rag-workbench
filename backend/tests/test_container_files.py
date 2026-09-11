from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_builds_frontend_and_starts_api() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM m.daocloud.io/docker.io/library/node:" in dockerfile
    assert "m.daocloud.io/docker.io/library/node" in dockerfile
    assert "m.daocloud.io/docker.io/library/python" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "FROM m.daocloud.io/docker.io/library/python:3.12" in dockerfile
    assert "download.pytorch.org/whl/cpu" in dockerfile
    assert "uvicorn" in dockerfile


def test_compose_uses_persistent_qdrant_and_api_data() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "qdrant/qdrant" in compose
    assert "m.daocloud.io/docker.io/qdrant/qdrant" in compose
    assert "EVIDENCE_RAG_QDRANT_MODE=server" in compose
    assert "EVIDENCE_RAG_QDRANT_URL=http://qdrant:6333" in compose
    assert "qdrant_storage:" in compose
    assert "app_data:" in compose
