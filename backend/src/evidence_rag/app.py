from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from evidence_rag.lifecycle import DocumentLifecycleService, LifecycleError
from evidence_rag.settings import Settings
from evidence_rag.vector_store import VectorIndex


class KnowledgeBaseCreate(BaseModel):
    name: str


def lifecycle_error(error: LifecycleError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


def create_app(
    settings: Settings | None = None,
    vector_index: VectorIndex | None = None,
) -> FastAPI:
    """创建 API 应用；后续路由以此工厂函数挂载，方便隔离测试配置。"""
    active_settings = settings or Settings()
    app = FastAPI(title="Evidence RAG Workbench API", version="0.1.0")
    app.state.settings = active_settings
    app.state.services = DocumentLifecycleService(active_settings, vector_index)

    @app.get("/api/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "qdrant_mode": active_settings.qdrant_mode}

    @app.post("/api/knowledge-bases", status_code=201)
    def create_knowledge_base(payload: KnowledgeBaseCreate) -> dict:
        try:
            return app.state.services.create_knowledge_base(payload.name)
        except LifecycleError as error:
            raise lifecycle_error(error) from error

    @app.get("/api/knowledge-bases")
    def list_knowledge_bases() -> list[dict]:
        return app.state.services.list_knowledge_bases()

    @app.delete("/api/knowledge-bases/{knowledge_base_id}", status_code=204)
    def delete_knowledge_base(knowledge_base_id: str) -> Response:
        try:
            app.state.services.delete_knowledge_base(knowledge_base_id)
        except LifecycleError as error:
            raise lifecycle_error(error) from error
        return Response(status_code=204)

    @app.post("/api/knowledge-bases/{knowledge_base_id}/documents", status_code=201)
    async def upload_document(
        knowledge_base_id: str,
        file: UploadFile = File(...),
    ) -> dict:
        try:
            return await app.state.services.upload_document(knowledge_base_id, file)
        except LifecycleError as error:
            raise lifecycle_error(error) from error

    @app.get("/api/knowledge-bases/{knowledge_base_id}/documents")
    def list_documents(knowledge_base_id: str) -> list[dict]:
        try:
            return app.state.services.list_documents(knowledge_base_id)
        except LifecycleError as error:
            raise lifecycle_error(error) from error

    @app.delete(
        "/api/knowledge-bases/{knowledge_base_id}/documents/{document_id}",
        status_code=204,
    )
    def delete_document(knowledge_base_id: str, document_id: str) -> Response:
        try:
            app.state.services.delete_document(knowledge_base_id, document_id)
        except LifecycleError as error:
            raise lifecycle_error(error) from error
        return Response(status_code=204)

    @app.post("/api/knowledge-bases/{knowledge_base_id}/documents/{document_id}/retry")
    def retry_document(knowledge_base_id: str, document_id: str) -> dict:
        try:
            return app.state.services.retry_document(knowledge_base_id, document_id)
        except LifecycleError as error:
            raise lifecycle_error(error) from error

    @app.get("/api/knowledge-bases/{knowledge_base_id}/documents/{document_id}/tasks")
    def list_document_tasks(knowledge_base_id: str, document_id: str) -> list[dict]:
        try:
            return app.state.services.list_tasks(knowledge_base_id, document_id)
        except LifecycleError as error:
            raise lifecycle_error(error) from error

    return app


app = create_app()
