import json
from pathlib import Path
from app.config import settings
from conftest import KEY, OTHER_AUTH


def test_content_lifecycle(client, monkeypatch):
    monkeypatch.setattr(settings(), 'content_admin_keys', KEY)
    path = '/api/admin/content/banner'
    data = {'draft': {'title': 'First', 'description': '<script>alert(1)</script>'}}
    assert client.post(path, json=data, headers=OTHER_AUTH).status_code == 403
    assert client.post(path, json=data).status_code == 200
    assert client.get('/api/content').json() == {'items': []}
    data['status'] = 'published'
    assert client.post(path, json=data).status_code == 200
    assert client.get('/api/content').json()['items'][0]['title'] == 'First'
    data['status'] = 'draft'
    data['draft']['title'] = 'Private draft'
    client.post(path, json=data)
    assert 'Private draft' not in client.get('/api/content').text
    data['status'] = 'published'
    client.post(path, json=data)
    assert client.get('/api/content').json()['items'][0]['title'] == 'Private draft'
    data['status'] = 'archived'
    client.post(path, json=data)
    assert client.get('/api/content').json()['items'] == []
    assert client.delete(path).status_code == 204
    assert client.delete(path).status_code == 404


def test_content_security(client, monkeypatch):
    monkeypatch.setattr(settings(), 'content_admin_keys', KEY)
    for url in ['javascript:alert(1)', '//evil.test', 'data:text/html,x', '/\\evil.test', 'https://user:pass@test.com']:
        assert client.post('/api/admin/content/x', json={'draft': {'image': url}}).status_code == 422
    assert client.post('/api/admin/content/x', json={'draft': {}, 'status': 'invalid'}).status_code == 422
    assert client.post('/api/admin/content/x', json={'draft': {}, 'position': -1}).status_code == 422
    client.headers.clear()
    assert client.get('/api/admin/content').status_code == 401
    assert client.post('/api/admin/content/x', json={'draft': {}}).status_code == 401
    assert client.get('/api/content').status_code == 200


def test_seed_integrity():
    defaults = json.loads((Path(__file__).parents[1] / 'app/content_defaults.json').read_text())
    assert defaults['login']['title'] == 'Your web, in focus.'
    assert set(defaults) == {'login', 'seo', 'Overview', 'AI Agent', 'Websites', 'Jobs', 'Workflows', 'Schedules'}

def test_migration_repeatability(tmp_path):
    import os
    import subprocess
    import sys
    from sqlalchemy import create_engine, text
    env = dict(os.environ, ADBOT_DATABASE_URL='sqlite:///' + str(tmp_path / 'migration.db'))
    for _ in range(2):
        result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                                cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    engine = create_engine(env['ADBOT_DATABASE_URL'])
    with engine.connect() as conn:
        assert conn.scalar(text('select count(*) from content_sections')) == 8
        assert conn.scalar(text('select count(*) from content_sections where published is null')) == 0
    engine.dispose()

def test_database_failure_is_structured(client, monkeypatch):
    from app import content
    from sqlalchemy.exc import SQLAlchemyError

    def unavailable():
        raise SQLAlchemyError('private database details')

    monkeypatch.setattr(content, 'Session', unavailable)
    response = client.get('/api/content')
    assert response.status_code == 503
    assert response.json() == {'detail': 'Website content is temporarily unavailable'}
    assert 'private database' not in response.text
