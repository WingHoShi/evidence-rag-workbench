import asyncio

import httpx

from evidence_rag.app import create_app
from evidence_rag.settings import Settings


def test_health_check_reports_local_qdrant_mode() -> None:
    app = create_app(Settings(qdrant_mode="local"))

    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get("/api/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "qdrant_mode": "local"}
