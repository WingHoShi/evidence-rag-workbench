from fastapi.testclient import TestClient

from evidence_rag.app import create_app
from evidence_rag.settings import Settings
from evidence_rag.vector_store import NoopVectorIndex


def test_app_serves_built_frontend_when_dist_directory_is_configured(tmp_path) -> None:
    (tmp_path / "index.html").write_text("<main>可信知识库工作台</main>", encoding="utf-8")
    settings = Settings(
        env="production",
        data_dir=tmp_path / "data",
        qdrant_path=tmp_path / "qdrant",
        frontend_dist_dir=tmp_path,
    )

    response = TestClient(create_app(settings=settings, vector_index=NoopVectorIndex())).get("/")

    assert response.status_code == 200
    assert "可信知识库工作台" in response.text
