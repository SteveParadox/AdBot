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
    data['revision']=client.get(path).json()['revision']
    data['status'] = 'published'
    assert client.post(path, json=data).status_code == 200
    assert client.get('/api/content').json()['items'][0]['title'] == 'First'
    data['revision']=client.get(path).json()['revision']
    data['status'] = 'draft'
    data['draft']['title'] = 'Private draft'
    client.post(path, json=data)
    assert 'Private draft' not in client.get('/api/content').text
    data['revision']=client.get(path).json()['revision']
    data['status'] = 'published'
    client.post(path, json=data)
    assert client.get('/api/content').json()['items'][0]['title'] == 'Private draft'
    data['revision']=client.get(path).json()['revision']
    data['status'] = 'archived'
    client.post(path, json=data)
    assert client.get('/api/content').json()['items'] == []
    assert client.delete(path,headers={"If-Match":client.get(path).json().get("revision","")}).status_code == 204
    assert client.delete(path,headers={"If-Match":client.get(path).json().get("revision","")}).status_code == 404


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
        assert conn.scalar(text('select count(distinct revision) from content_sections')) == 8
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

def test_stale_save_publish_delete_and_recreate(client,monkeypatch):
    monkeypatch.setattr(settings(),'content_admin_keys',KEY)
    path='/api/admin/content/conflict'
    first=client.post(path,json={'draft':{'title':'First'},'status':'published'}).json()
    second=client.post(path,json={'revision':first['revision'],'draft':{'title':'Newer'},'status':'published'})
    assert second.status_code==200
    current=second.json()
    for status in ['draft','published','archived']:
        assert client.post(path,json={'revision':first['revision'],'draft':{'title':'STALE'},'status':status}).status_code==409
    assert client.post(path,json={'draft':{}}).status_code==428
    assert client.delete(path).status_code==428
    assert client.delete(path,headers={'If-Match':first['revision']}).status_code==409
    assert client.get(path).json()['draft']['title']=='Newer'
    assert client.get('/api/content').json()['items'][0]['title']=='Newer'
    assert client.delete(path,headers={'If-Match':current['revision']}).status_code==204
    assert client.post(path,json={'revision':current['revision'],'draft':{}}).status_code==409
    recreated=client.post(path,json={'draft':{'title':'Recreated'}}).json()
    assert recreated['revision'] not in {first['revision'],current['revision']}
    assert client.post(path,json={'revision':current['revision'],'draft':{'title':'Old'}}).status_code==409


def test_simultaneous_writers_only_one_wins(client,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    monkeypatch.setattr(settings(),'content_admin_keys',KEY)
    path='/api/admin/content/race'
    revision=client.post(path,json={'draft':{}}).json()['revision']
    barrier=threading.Barrier(2)
    def write(title):
        barrier.wait()
        return client.post(path,json={'revision':revision,'draft':{'title':title},'status':'published'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(write,['Left','Right']))
    assert sorted(r.status_code for r in responses)==[200,409]
    winner=next(r.json() for r in responses if r.status_code==200)
    assert client.get(path).json()['revision']==winner['revision']
    assert client.get('/api/content').json()['items'][0]['title']==winner['draft']['title']

def test_revision_migration_preserves_existing_drafts(tmp_path):
    import os
    import subprocess
    import sys
    from sqlalchemy import create_engine, text
    env=dict(os.environ,ADBOT_DATABASE_URL='sqlite:///'+str(tmp_path/'existing.db'))
    def migrate(*args):
        result=subprocess.run([sys.executable,'-m','alembic',*args],cwd=Path(__file__).parents[1],env=env,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    migrate('upgrade','e18a00000001')
    engine=create_engine(env['ADBOT_DATABASE_URL'])
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO content_sections (key,status,position,draft,published,updated_at) VALUES ('custom','draft',17,:draft,:published,123)"),
                           {'draft':json.dumps({'title':'Private edit'}),'published':json.dumps({'title':'Live version'})})
    migrate('upgrade','head')
    migrate('upgrade','head')
    with engine.connect() as connection:
        row=connection.execute(text("SELECT * FROM content_sections WHERE key='custom'")).mappings().one()
        assert json.loads(row['draft'])=={'title':'Private edit'}
        assert json.loads(row['published'])=={'title':'Live version'}
        assert row['position']==17 and row['updated_at']==123 and len(row['revision'])==36
    migrate('downgrade','e18a00000001')
    with engine.connect() as connection:
        assert json.loads(connection.scalar(text("SELECT draft FROM content_sections WHERE key='custom'")))=={'title':'Private edit'}
    engine.dispose()
