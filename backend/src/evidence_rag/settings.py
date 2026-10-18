from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """表示运行时所需的本地配置不完整。"""


class Settings(BaseSettings):
    """只从本机环境变量或 .env 读取的应用配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="EVIDENCE_RAG_",
        extra="ignore",
    )

    env: Literal["development", "production", "test"] = "development"
    data_dir: Path = Path("data")
    max_file_bytes: int = 20 * 1024 * 1024
    max_knowledge_base_bytes: int = 100 * 1024 * 1024
    embedding_model: str = "AI-ModelScope/multilingual-e5-small"
    embedding_model_dir: Path = Path("models/multilingual-e5-small")
    embedding_batch_size: int = 16
    qdrant_mode: Literal["local", "server"] = "local"
    qdrant_path: Path = Path("data/qdrant")
    qdrant_url: str | None = None
    frontend_dist_dir: Path = Path("frontend/dist")
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    model_config_path: Path = Path("runtime-config/model.json")
    retrieval_min_vector_score: float = 0.55

    @property
    def database_path(self) -> Path:
        return self.data_dir / "evidence_rag.db"

    @model_validator(mode="after")
    def validate_qdrant_configuration(self) -> "Settings":
        if self.qdrant_mode == "server" and not self.qdrant_url:
            raise ValueError(
                "EVIDENCE_RAG_QDRANT_URL is required when "
                "EVIDENCE_RAG_QDRANT_MODE=server"
            )
        return self

    def require_llm_credentials(self) -> tuple[str, str, str]:
        """在实际调用生成模型前验证必要配置，避免密钥进入前端。"""
        if not self.llm_base_url:
            raise ConfigurationError("EVIDENCE_RAG_LLM_BASE_URL is not configured")
        if not self.llm_api_key:
            raise ConfigurationError("EVIDENCE_RAG_LLM_API_KEY is not configured")
        if not self.llm_model:
            raise ConfigurationError("EVIDENCE_RAG_LLM_MODEL is not configured")
        return self.llm_base_url, self.llm_api_key, self.llm_model
