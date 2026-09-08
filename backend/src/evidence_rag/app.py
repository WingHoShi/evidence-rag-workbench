import json

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from evidence_rag.answering import GroundedAnswerService, OpenAICompatibleChatClient
from evidence_rag.indexing import DocumentIndexingService, MultilingualE5EmbeddingEngine, QdrantChunkIndex
from evidence_rag.lifecycle import DocumentLifecycleService, LifecycleError
from evidence_rag.retrieval import HybridRetriever
from evidence_rag.settings import Settings
from evidence_rag.vector_store import VectorIndex


class KnowledgeBaseCreate(BaseModel):
    name: str


class ChatQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)
    top_k: int = Field(default=5, ge=1, le=5)

def lifecycle_error(error: LifecycleError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


def create_app(
    settings: Settings | None = None,
    vector_index: VectorIndex | None = None,
    embedding_engine=None,
    chat_client=None,
) -> FastAPI:
    """创建 API 应用；后续路由以此工厂函数挂载，方便隔离测试配置。"""
    active_settings = settings or Settings()
    app = FastAPI(title="Evidence RAG Workbench API", version="0.1.0")
    app.state.settings = active_settings
    active_index = vector_index or QdrantChunkIndex(active_settings)
    app.state.services = DocumentLifecycleService(active_settings, active_index)
    app.state.indexing_service = DocumentIndexingService(
        app.state.services,
        active_index,
        embedding_engine or MultilingualE5EmbeddingEngine(active_settings),
    )
    app.state.retriever = HybridRetriever(
        app.state.indexing_service,
        active_index,
        min_vector_score=active_settings.retrieval_min_vector_score,
    )
    app.state.answer_service = GroundedAnswerService(
        app.state.retriever,
        chat_client or OpenAICompatibleChatClient(active_settings),
    )

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

    @app.post("/api/knowledge-bases/{knowledge_base_id}/documents/{document_id}/index")
    def index_document(knowledge_base_id: str, document_id: str) -> dict:
        try:
            return app.state.indexing_service.index_document(knowledge_base_id, document_id)
        except LifecycleError as error:
            raise lifecycle_error(error) from error

    @app.post("/api/knowledge-bases/{knowledge_base_id}/rebuild-index")
    def rebuild_index(knowledge_base_id: str) -> dict:
        try:
            return app.state.indexing_service.rebuild_knowledge_base(knowledge_base_id)
        except LifecycleError as error:
            raise lifecycle_error(error) from error

    @app.get("/api/knowledge-bases/{knowledge_base_id}/index-status")
    def index_status(knowledge_base_id: str) -> dict:
        try:
            return app.state.indexing_service.index_status(knowledge_base_id)
        except LifecycleError as error:
            raise lifecycle_error(error) from error

    @app.post("/api/knowledge-bases/{knowledge_base_id}/chat/stream")
    async def stream_answer(knowledge_base_id: str, payload: ChatQuestion) -> StreamingResponse:
        try:
            app.state.services._require_knowledge_base(knowledge_base_id)
        except LifecycleError as error:
            raise lifecycle_error(error) from error

        async def events():
            async for event, data in app.state.answer_service.stream_events(
                knowledge_base_id,
                payload.question,
                top_k=payload.top_k,
            ):
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


app = create_app()
