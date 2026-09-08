import pytest
from pydantic import ValidationError

from evidence_rag.settings import ConfigurationError, Settings


def test_server_qdrant_mode_requires_url() -> None:
    with pytest.raises(ValidationError, match="EVIDENCE_RAG_QDRANT_URL"):
        Settings(qdrant_mode="server")


def test_llm_credentials_raise_clear_error_when_api_key_is_missing() -> None:
    settings = Settings(llm_base_url="https://api.example.com/v1", llm_api_key=None)

    with pytest.raises(ConfigurationError, match="EVIDENCE_RAG_LLM_API_KEY"):
        settings.require_llm_credentials()
