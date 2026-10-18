import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from evidence_rag.model_config import ModelConfigStore
from evidence_rag.model_config_routes import create_model_config_router
from evidence_rag.settings import Settings


SECRET = 'test-private-token-never-return'


@pytest.fixture
def store(tmp_path):
    return ModelConfigStore(Settings(_env_file=None, model_config_path=tmp_path / 'model.json'))


def request(store, method='GET', path='/api/model-config', *, transport=None, **kwargs):
    app = FastAPI()
    app.include_router(create_model_config_router(store, transport=transport))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1:8000') as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(run())


def payload(**overrides):
    return {'base_url': 'https://api.deepseek.com', 'model': 'deepseek-flash', 'api_key': SECRET, **overrides}


def test_save_and_status_never_return_key_or_call_provider(store):
    def fail(request):
        raise AssertionError('Saving must not call provider')
    result = request(store, 'PUT', json=payload(), transport=httpx.MockTransport(fail))
    assert result.status_code == 200
    assert result.json()['configured'] is True
    assert result.json()['source'] == 'file'
    assert SECRET not in result.text
    result = request(store)
    assert result.status_code == 200
    assert 'api_key' not in result.json()
    assert result.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('headers', [
    {'origin': 'https://evil.example'}, {'origin': 'null'}, {'host': 'evil.example'},
    {'sec-fetch-site': 'cross-site'}, {'origin': 'http://127.0.0.1:6666'},
])
def test_cross_site_requests_rejected_before_save(store, headers):
    result = request(store, 'PUT', json=payload(), headers=headers)
    assert result.status_code == 403
    assert not store.path.exists()


@pytest.mark.parametrize('origin', ['http://127.0.0.1:8000', 'http://localhost:5173'])
def test_local_same_origin_and_explicit_vite_origin_allowed(store, origin):
    assert request(store, 'PUT', json=payload(), headers={'origin': origin}).status_code == 200


@pytest.mark.parametrize('body', [payload(api_key=[SECRET]), payload(extra=SECRET),
    payload(base_url='https://user:' + SECRET + '@example.com'), {'api_key': SECRET}])
def test_bad_input_does_not_echo_secrets(store, body):
    result = request(store, 'PUT', json=body)
    assert result.status_code in {400, 422}
    assert SECRET not in result.text


def test_oversized_or_non_json_requests_rejected(store):
    assert request(store, 'PUT', content='x' * 20000, headers={'content-type':'application/json'}).status_code == 413
    assert request(store, 'PUT', content='api_key=' + SECRET).status_code == 415


def test_corrupt_config_status_is_safe(store):
    store.path.write_text(SECRET, encoding='utf-8')
    result = request(store)
    assert result.status_code == 400
    assert SECRET not in result.text


def test_non_utf8_config_status_is_safe(store):
    store.path.write_bytes(b'\xff\xfe\x00\x80')
    result = request(store)
    assert result.status_code == 400
    assert 'UnicodeDecodeError' not in result.text


def test_connection_test_uses_short_prompt_and_does_not_save(store):
    seen = []
    def respond(req):
        seen.append(req)
        return httpx.Response(200, json={'choices':[{'message':{'content':'OK'},'finish_reason':'stop'}]})
    result = request(store, 'POST', '/api/model-config/test', json=payload(), transport=httpx.MockTransport(respond))
    assert result.status_code == 200
    assert result.json() == {'ok': True}
    assert not store.path.exists()
    assert len(seen) == 1
    data = json.loads(seen[0].content)
    assert data['stream'] is False and data['max_tokens'] == 16
    assert seen[0].headers['authorization'] == 'Bearer ' + SECRET
    assert data['messages'] == [{'role':'user','content':'Reply with OK.'}]


@pytest.mark.parametrize('status,body', [(401, {'error':SECRET}), (429, {'error':SECRET}),
    (500, {'error':SECRET}), (302, {}), (200, {'choices':[]}),
    (200, {'choices':[{'message':{'reasoning_content':'private thought'}}]}), (200, [])])
def test_provider_errors_safe_no_retry_or_save(store, status, body):
    calls = []
    def respond(req):
        calls.append(req)
        return httpx.Response(status, json=body, headers={'location': 'https://evil.example'})
    result = request(store, 'POST', '/api/model-config/test', json=payload(), transport=httpx.MockTransport(respond))
    assert result.status_code == 400
    assert SECRET not in result.text
    assert len(calls) == 1 and not store.path.exists()


def test_timeout_safe_and_existing_configuration_unchanged(store):
    store.save('https://api.deepseek.com', 'old-model', SECRET)
    def timeout(req):
        raise httpx.ReadTimeout(SECRET)
    result = request(store, 'POST', '/api/model-config/test', json=payload(), transport=httpx.MockTransport(timeout))
    assert result.status_code == 400 and SECRET not in result.text
    assert store.resolve().model == 'old-model'


def test_app_saved_configuration_used_by_next_generation(tmp_path):
    from evidence_rag.app import create_app
    settings = Settings(_env_file=None, data_dir=tmp_path / 'data',
        qdrant_path=tmp_path / 'vectors', model_config_path=tmp_path / 'model.json')
    app = create_app(settings)
    seen = []
    def respond(req):
        seen.append((req.headers['authorization'], json.loads(req.content)['model']))
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n')
    model_client = app.state.answer_service.chat_client
    model_client.transport = httpx.MockTransport(respond)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1:8000') as client:
            result = await client.put('/api/model-config', json=payload())
            assert result.status_code == 200
            assert [text async for text in model_client.stream([{'role':'user','content':'test'}])] == ['OK']
            result = await client.put('/api/model-config', json=payload(model='updated-model', api_key=''))
            assert result.status_code == 200
            assert [text async for text in model_client.stream([{'role':'user','content':'test'}])] == ['OK']
    asyncio.run(run())
    assert seen == [('Bearer ' + SECRET, 'deepseek-flash'), ('Bearer ' + SECRET, 'updated-model')]
