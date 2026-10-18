import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from evidence_rag.answering import OpenAICompatibleChatClient
from evidence_rag.model_config import ModelConfigStore
from evidence_rag.settings import ConfigurationError, Settings


@pytest.fixture
def store(tmp_path):
    return ModelConfigStore(Settings(_env_file=None, model_config_path=tmp_path / 'model.json',
        llm_base_url='https://old.example', llm_model='old-model', llm_api_key='test-old-secret'))


def test_environment_fallback_and_redacted_status(store):
    assert store.resolve().model == 'old-model'
    assert store.status() == {'configured': True, 'base_url': 'https://old.example',
                              'model': 'old-model', 'source': 'environment'}
    assert 'test-old-secret' not in repr(store.resolve())


def test_save_reload_and_blank_key_retention(store):
    store.save('https://api.deepseek.com/', 'deepseek-flash', 'test-new-secret')
    reloaded = ModelConfigStore(store.settings)
    assert reloaded.resolve().api_key.get_secret_value() == 'test-new-secret'
    reloaded.save('https://api.deepseek.com', 'another-model', None)
    assert reloaded.resolve().model == 'another-model'
    assert reloaded.resolve().api_key.get_secret_value() == 'test-new-secret'
    assert 'test-new-secret' not in json.dumps(reloaded.status())


def test_changed_address_requires_new_key(store):
    with pytest.raises(ConfigurationError):
        store.save('https://other.example', 'new-model', '')
    assert not store.path.exists()


@pytest.mark.parametrize('url', ['http://remote.example', 'https://user:pass@example.com',
    'https://example.com?key=secret', 'https://example.com/#x', 'https://example.com\n',
    'ftp://example.com', 'https://example.com:wrong', 'https://example.com/../escape'])
def test_rejects_unsafe_urls(store, url):
    with pytest.raises(ConfigurationError):
        store.save(url, 'model', 'test-secret')


def test_local_http_service_allowed(store):
    store.save('http://127.0.0.1:1234/v1', 'local-model', 'test-local')
    assert store.resolve().base_url == 'http://127.0.0.1:1234/v1'


def test_corrupt_config_does_not_silently_fallback(store):
    store.path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ConfigurationError):
        store.resolve()


@pytest.mark.parametrize('raw', [b'\xff\xfe\x00\x80', '{"api_key":"test-private"}'.encode('utf-16')])
def test_non_utf8_config_raises_safe_configuration_error(store, raw):
    store.path.write_bytes(raw)
    with pytest.raises(ConfigurationError):
        store.status()


def test_non_utf8_config_becomes_safe_model_error(store):
    from evidence_rag.answering import ModelProviderError
    store.path.write_bytes(b'\xff\xfe\x00\x80')
    async def run():
        client = OpenAICompatibleChatClient(store.settings, config_store=store)
        return [text async for text in client.stream([{'role':'user','content':'test'}])]
    with pytest.raises(ModelProviderError, match='模型配置不完整'):
        asyncio.run(run())


def test_failed_atomic_replace_preserves_previous_file(store):
    store.save('https://old.example', 'saved-model', 'test-saved-secret')
    original = store.path.read_bytes()
    with patch('evidence_rag.model_config.os.replace', side_effect=OSError('failure')):
        with pytest.raises(ConfigurationError):
            store.save('https://new.example', 'new-model', 'test-new-secret')
    assert store.path.read_bytes() == original
    assert list(store.path.parent.iterdir()) == [store.path]


def test_model_client_reads_snapshot_for_each_request(store):
    seen = []
    def respond(request):
        seen.append((request.headers['Authorization'], json.loads(request.content)['model']))
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')
    async def run():
        client = OpenAICompatibleChatClient(store.settings, config_store=store,
                                            transport=httpx.MockTransport(respond))
        assert [s async for s in client.stream([{'role':'user','content':'test'}])] == ['ok']
        store.save('https://new.example', 'new-model', 'test-new-secret')
        assert [s async for s in client.stream([{'role':'user','content':'test'}])] == ['ok']
    asyncio.run(run())
    assert seen == [('Bearer test-old-secret', 'old-model'), ('Bearer test-new-secret', 'new-model')]


def test_missing_credentials_are_not_configured(tmp_path):
    store = ModelConfigStore(Settings(_env_file=None, model_config_path=tmp_path / 'absent.json'))
    assert store.status()['configured'] is False
    with pytest.raises(ConfigurationError):
        store.save('https://api.deepseek.com', 'deepseek-flash', '')


def test_invalid_environment_key_not_reported_as_usable(store):
    store.settings.llm_api_key = 'test-密钥'
    assert store.status()['configured'] is False
    with pytest.raises(ConfigurationError):
        store.resolve()


def test_active_request_keeps_its_config_snapshot(store):
    seen = []
    class UpdateDuringStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
            store.save('https://new.example', 'new-model', 'test-new-secret')
            yield b'data: {"choices":[{"delta":{"content":"second"}}]}\n\ndata: [DONE]\n\n'
    def respond(request):
        seen.append(request.headers['authorization'])
        return httpx.Response(200, stream=UpdateDuringStream())
    async def run():
        client = OpenAICompatibleChatClient(store.settings, config_store=store, transport=httpx.MockTransport(respond))
        return [s async for s in client.stream([{'role':'user','content':'test'}])]
    assert asyncio.run(run()) == ['first', 'second']
    assert seen == ['Bearer test-old-secret']
    assert store.resolve().model == 'new-model'


def test_model_client_refuses_redirect_without_forwarding_key(store):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(302, headers={'location':'https://evil.example'})
    async def run():
        client = OpenAICompatibleChatClient(store.settings, config_store=store, transport=httpx.MockTransport(respond))
        return [s async for s in client.stream([{'role':'user','content':'test'}])]
    from evidence_rag.answering import ModelProviderError
    with pytest.raises(ModelProviderError):
        asyncio.run(run())
    assert len(seen) == 1
