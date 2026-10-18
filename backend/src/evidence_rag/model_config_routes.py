"""只面向本机的模型配置接口；不返回原始校验错误或上游正文。"""
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from evidence_rag.model_config import ModelConfigStore
from evidence_rag.settings import ConfigurationError


class ModelConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(max_length=2048)
    model: str = Field(max_length=200)
    api_key: SecretStr | None = None


def _local_request(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    try:
        host = urlsplit(f"http://{request.headers.get('host', '')}")
        if host.hostname not in {"localhost", "127.0.0.1", "::1"} or host.username or host.password:
            raise ValueError
        port = host.port or (443 if request.url.scheme == "https" else 80)
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            same = (parsed.scheme == request.url.scheme and parsed.hostname == host.hostname and origin_port == port)
            dev = (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                   and origin_port == 5173)
            if (not (same or dev) or parsed.path or parsed.query or parsed.fragment
                    or parsed.username or parsed.password):
                raise ValueError
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise ValueError
    except ValueError:
        raise HTTPException(403, "模型配置仅允许本机同源访问。", headers={"Cache-Control": "no-store"}) from None


async def _payload(request: Request) -> ModelConfigRequest:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "请使用 JSON 提交配置。")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise HTTPException(413, "模型配置内容过大。")
    try:
        return ModelConfigRequest.model_validate_json(body)
    except (ValidationError, ValueError):
        raise HTTPException(422, "配置格式无效，请检查地址、模型名和 API Key。") from None


def create_model_config_router(store: ModelConfigStore, *, transport: httpx.AsyncBaseTransport | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/model-config", dependencies=[Depends(_local_request)])

    @router.get("")
    def status() -> dict:
        try:
            return store.status()
        except ConfigurationError as error:
            raise HTTPException(400, str(error), headers={"Cache-Control": "no-store"}) from None

    @router.put("")
    async def save(request: Request) -> dict:
        data = await _payload(request)
        try:
            return store.save(data.base_url, data.model, data.api_key.get_secret_value() if data.api_key else None)
        except ConfigurationError as error:
            raise HTTPException(400, str(error), headers={"Cache-Control": "no-store"}) from None

    @router.post("/test")
    async def test_connection(request: Request) -> dict:
        data = await _payload(request)
        try:
            config = store.prepare(data.base_url, data.model, data.api_key.get_secret_value() if data.api_key else None)
            async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=transport) as client:
                result = await client.post(f"{config.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {config.api_key.get_secret_value()}"},
                    json={"model": config.model, "messages": [{"role": "user", "content": "Reply with OK."}],
                          "max_tokens": 16, "stream": False})
            if result.status_code == 401 or result.status_code == 403:
                raise ConfigurationError("鉴权失败，请检查自己的 API Key 和模型权限。")
            if result.status_code == 429:
                raise ConfigurationError("模型服务限流或额度不足，请检查账户后重试。")
            if result.status_code != 200:
                raise ConfigurationError("模型服务未正常响应，请检查地址和模型名称。")
            try:
                content = result.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError
            except (ValueError, TypeError, KeyError, IndexError):
                raise ConfigurationError("未收到有效的模型回复，请检查模型名称或输出限制。") from None
            return {"ok": True}
        except ConfigurationError as error:
            raise HTTPException(400, str(error), headers={"Cache-Control": "no-store"}) from None
        except httpx.HTTPError:
            raise HTTPException(400, "连接模型服务失败或超时，请检查网络及配置。", headers={"Cache-Control": "no-store"}) from None

    return router
