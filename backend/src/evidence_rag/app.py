from fastapi import FastAPI

from evidence_rag.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建 API 应用；后续路由以此工厂函数挂载，方便隔离测试配置。"""
    active_settings = settings or Settings()
    app = FastAPI(title="Evidence RAG Workbench API", version="0.1.0")
    app.state.settings = active_settings

    @app.get("/api/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "qdrant_mode": active_settings.qdrant_mode}

    return app


app = create_app()
