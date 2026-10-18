"""本机模型配置；响应只使用 status()，不得序列化含密钥的配置。"""
from __future__ import annotations

import ipaddress
import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from evidence_rag.settings import ConfigurationError, Settings


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str
    model: str
    api_key: SecretStr


def validate_base_url(value: str) -> str:
    try:
        if any(ord(char) < 33 or ord(char) == 127 for char in value) or "\\" in value:
            raise ValueError
        parsed = urlsplit(value)
        host = parsed.hostname
        _ = parsed.port
        if (parsed.scheme not in {"http", "https"} or not host or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or "?" in value or "#" in value
                or any(part in {".", ".."} for part in unquote(parsed.path).split("/"))):
            raise ValueError
        loopback = host == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if parsed.scheme == "http" and not loopback:
            raise ValueError
    except (ValueError, TypeError):
        raise ConfigurationError("接口地址无效：远程服务须使用 HTTPS，且不能包含账号、参数或片段。") from None
    return value.rstrip("/")


def make_config(base_url: str, model: str, api_key: str) -> ModelConfig:
    base_url = validate_base_url(base_url)
    model, api_key = model.strip(), api_key.strip()
    if (not model or not api_key or len(model) > 200 or len(api_key) > 4096
            or not api_key.isascii()
            or any(ord(char) < 33 or ord(char) == 127 for char in api_key)
            or any(ord(char) < 32 or ord(char) == 127 for char in model)):
        raise ConfigurationError("请填写有效的模型名称和 API Key。")
    return ModelConfig(base_url=base_url, model=model, api_key=SecretStr(api_key))


class ModelConfigStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path: Path = settings.model_config_path
        self._lock = RLock()

    def _read(self) -> ModelConfig | None:
        if self.path.is_symlink():
            raise ConfigurationError("模型配置文件不能是符号链接。")
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except UnicodeError:
            raise ConfigurationError("本机模型配置编码损坏，请以 UTF-8 保存后重试。") from None
        except OSError:
            raise ConfigurationError("无法读取本机模型配置。") from None
        try:
            parsed = ModelConfig.model_validate_json(raw)
            return make_config(parsed.base_url, parsed.model, parsed.api_key.get_secret_value())
        except (ValidationError, ConfigurationError, ValueError):
            raise ConfigurationError("本机模型配置损坏，请修复配置文件后重试。") from None

    def resolve(self) -> ModelConfig:
        with self._lock:
            saved = self._read()
            if saved:
                return saved
            base_url, key, model = self.settings.require_llm_credentials()
            return make_config(base_url, model, key)

    def status(self) -> dict:
        with self._lock:
            saved = self._read()
            if saved:
                return {"configured": True, "base_url": saved.base_url, "model": saved.model, "source": "file"}
            # Only expose validated public values, never arbitrary environment strings.
            base = self.settings.llm_base_url or ""
            model = self.settings.llm_model or ""
            try:
                base = validate_base_url(base)
            except ConfigurationError:
                base = ""
            if any(ord(c) < 32 for c in model) or len(model) > 200:
                model = ""
            try:
                self.resolve()
                configured = True
            except ConfigurationError:
                configured = False
            return {"configured": configured,
                    "base_url": base, "model": model,
                    "source": "environment" if base or model or self.settings.llm_api_key else "none"}

    def prepare(self, base_url: str, model: str, api_key: str | None) -> ModelConfig:
        with self._lock:
            base_url = validate_base_url(base_url)
            if not api_key or not api_key.strip():
                current = self.resolve()
                if current.base_url != base_url:
                    raise ConfigurationError("更换接口地址时必须重新输入 API Key。")
                api_key = current.api_key.get_secret_value()
            return make_config(base_url, model, api_key)

    def save(self, base_url: str, model: str, api_key: str | None) -> dict:
        with self._lock:
            config = self.prepare(base_url, model, api_key)
            if self.path.is_symlink():
                raise ConfigurationError("模型配置文件不能是符号链接。")
            temporary = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd, temporary = tempfile.mkstemp(prefix=".model-", dir=self.path.parent)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump({"base_url": config.base_url, "model": config.model,
                               "api_key": config.api_key.get_secret_value()}, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            except OSError:
                raise ConfigurationError("无法保存本机模型配置，原配置未被替换。") from None
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            return self.status()
