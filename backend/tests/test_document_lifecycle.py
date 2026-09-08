import asyncio
from pathlib import Path

import httpx
import pytest

from evidence_rag.app import create_app
from evidence_rag.settings import Settings


class RecordingVectorIndex:
    def __init__(self) -> None:
        self.deleted_documents: list[tuple[str, str]] = []
        self.deleted_knowledge_bases: list[str] = []

    def delete_document_vectors(self, knowledge_base_id: str, version_id: str) -> None:
        self.deleted_documents.append((knowledge_base_id, version_id))

    def delete_knowledge_base_vectors(self, knowledge_base_id: str) -> None:
        self.deleted_knowledge_bases.append(knowledge_base_id)


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        qdrant_path=tmp_path / "data" / "qdrant",
        max_file_bytes=3,
        max_knowledge_base_bytes=5,
    )
    vector_index = RecordingVectorIndex()
    application = create_app(settings, vector_index=vector_index)
    application.state.recording_vector_index = vector_index
    return application


def request(app, method: str, url: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def create_knowledge_base(app, name: str) -> dict:
    response = request(app, "POST", "/api/knowledge-bases", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def upload(app, knowledge_base_id: str, filename: str, content: bytes) -> httpx.Response:
    return request(
        app,
        "POST",
        f"/api/knowledge-bases/{knowledge_base_id}/documents",
        files={"file": (filename, content, "application/octet-stream")},
    )


def test_creates_and_lists_knowledge_bases(app) -> None:
    created = create_knowledge_base(app, "LangGraph 官方文档")

    response = request(app, "GET", "/api/knowledge-bases")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": created["id"],
            "name": "LangGraph 官方文档",
            "document_count": 0,
        }
    ]


def test_upload_copies_supported_file_and_enqueues_parse_task(app) -> None:
    knowledge_base = create_knowledge_base(app, "个人资料")

    response = upload(knowledge_base_id=knowledge_base["id"], app=app, filename="notes.md", content=b"abc")

    assert response.status_code == 201, response.text
    document = response.json()
    assert document["original_filename"] == "notes.md"
    assert document["status"] == "queued"
    assert document["task"]["kind"] == "parse"
    assert document["task"]["status"] == "queued"
    stored_path = Path(app.state.services.storage_path_for(document["id"]))
    assert stored_path.read_bytes() == b"abc"


def test_rejects_unsupported_and_oversized_files(app) -> None:
    knowledge_base = create_knowledge_base(app, "限制测试")

    unsupported = upload(app, knowledge_base["id"], "malware.exe", b"a")
    oversized = upload(app, knowledge_base["id"], "large.txt", b"abcd")

    assert unsupported.status_code == 422
    assert "支持" in unsupported.json()["detail"]
    assert oversized.status_code == 413


def test_prevents_duplicate_hash_within_one_knowledge_base_but_not_another(app) -> None:
    first = create_knowledge_base(app, "知识库 A")
    second = create_knowledge_base(app, "知识库 B")

    original = upload(app, first["id"], "a.txt", b"abc")
    duplicate = upload(app, first["id"], "renamed.txt", b"abc")
    another_knowledge_base = upload(app, second["id"], "same.txt", b"abc")

    assert original.status_code == 201
    assert duplicate.status_code == 409
    assert another_knowledge_base.status_code == 201


def test_enforces_knowledge_base_size_and_does_not_leak_documents_between_bases(app) -> None:
    first = create_knowledge_base(app, "知识库 A")
    second = create_knowledge_base(app, "知识库 B")
    uploaded = upload(app, first["id"], "first.txt", b"abc")

    capacity_exceeded = upload(app, first["id"], "second.txt", b"def")
    other_documents = request(app, "GET", f"/api/knowledge-bases/{second['id']}/documents")
    cross_base_delete = request(
        app,
        "DELETE",
        f"/api/knowledge-bases/{second['id']}/documents/{uploaded.json()['id']}",
    )

    assert capacity_exceeded.status_code == 413
    assert other_documents.json() == []
    assert cross_base_delete.status_code == 404


def test_delete_document_removes_owned_copy_and_requests_vector_cleanup(app) -> None:
    knowledge_base = create_knowledge_base(app, "删除测试")
    created = upload(app, knowledge_base["id"], "source.txt", b"abc").json()
    stored_path = Path(app.state.services.storage_path_for(created["id"]))

    response = request(
        app,
        "DELETE",
        f"/api/knowledge-bases/{knowledge_base['id']}/documents/{created['id']}",
    )

    assert response.status_code == 204
    assert not stored_path.exists()
    assert app.state.recording_vector_index.deleted_documents == [
        (knowledge_base["id"], created["version_id"])
    ]
    assert request(app, "GET", f"/api/knowledge-bases/{knowledge_base['id']}/documents").json() == []


def test_retry_creates_a_new_queued_parse_task_after_failure(app) -> None:
    knowledge_base = create_knowledge_base(app, "重试测试")
    document = upload(app, knowledge_base["id"], "source.txt", b"abc").json()
    app.state.services.mark_latest_task_failed(document["id"], "解析器暂不可用")

    retry = request(
        app,
        "POST",
        f"/api/knowledge-bases/{knowledge_base['id']}/documents/{document['id']}/retry",
    )
    tasks = request(
        app,
        "GET",
        f"/api/knowledge-bases/{knowledge_base['id']}/documents/{document['id']}/tasks",
    )

    assert retry.status_code == 200
    assert retry.json()["status"] == "queued"
    assert retry.json()["retry_count"] == 1
    assert [task["status"] for task in tasks.json()] == ["failed", "queued"]


def test_delete_knowledge_base_removes_its_document_copies_and_vector_scope(app) -> None:
    knowledge_base = create_knowledge_base(app, "删除知识库")
    document = upload(app, knowledge_base["id"], "source.txt", b"abc").json()
    stored_path = Path(app.state.services.storage_path_for(document["id"]))

    response = request(app, "DELETE", f"/api/knowledge-bases/{knowledge_base['id']}")

    assert response.status_code == 204
    assert not stored_path.exists()
    assert app.state.recording_vector_index.deleted_knowledge_bases == [knowledge_base["id"]]
    assert request(app, "GET", "/api/knowledge-bases").json() == []


def test_sqlite_schema_preserves_future_session_and_citation_tables(app) -> None:
    table_names = app.state.services.database.table_names()

    assert {
        "knowledge_bases",
        "documents",
        "document_versions",
        "document_tasks",
        "chat_sessions",
        "chat_messages",
        "citation_snapshots",
    }.issubset(table_names)
