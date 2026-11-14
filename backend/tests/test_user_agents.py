import pytest
from pydantic import ValidationError
from app.config import settings
from app.user_agents import Document, Profile, resolve, validate
from conftest import KEY, OTHER_AUTH


def test_validation_and_precedence(client,monkeypatch):
    monkeypatch.setattr(settings(),'content_admin_keys',KEY)
    assert resolve('browser')==settings().user_agent_default
    data=client.get('/api/admin/user-agents').json()
    assert client.get('/api/admin/user-agents',headers=OTHER_AUTH).status_code==403
    doc={k:data[k] for k in ('revision','global_value','profiles','services')}
    doc['global_value']='Custom legitimate client / 7.0 (test)'
    doc['profiles'].append(dict(id='custom',name='Custom',value='Profile/2'))
    doc['services']={'ai':{'profile':'custom'},'browser':{'value':'Browser/3'}}
    response=client.post('/api/admin/user-agents',json=doc)
    assert response.status_code==200,response.text
    assert resolve('browser')=='Browser/3'
    assert resolve('ai')=='Profile/2'
    assert resolve('ai_local')==doc['global_value']
    with pytest.raises(PermissionError):
        resolve('ai',override='PerRequest/1')
    monkeypatch.setattr(settings(),'user_agent_allow_request_overrides',True)
    assert resolve('ai',override='PerRequest/1',authorized=True)=='PerRequest/1'
    monkeypatch.setattr(settings(),'user_agent_fixed_identities',{'ai':'Mandatory/1'})
    assert resolve('ai',override='PerRequest/1',authorized=True)=='Mandatory/1'
    assert client.post('/api/admin/user-agents',json=doc).status_code==409
    client.headers.clear()
    assert client.get('/api/admin/user-agents').status_code==401


@pytest.mark.parametrize('value',['','bad\r\nX: injected','bad\x00','bad\tvalue','café',' leading','trailing ','x'*513])
def test_invalid_values(value):
    with pytest.raises(ValueError):
        validate(value)
    with pytest.raises(ValidationError):
        Profile(id='bad',name='Bad',value=value)


def test_profiles_and_rotation(client,monkeypatch):
    monkeypatch.setattr(settings(),'content_admin_keys',KEY)
    monkeypatch.setattr(settings(),'user_agent_rotatable_services','browser')
    data={'revision':0,'global_value':'Global/1','profiles':[{'id':'a','name':'A','value':'Alpha/1'}, {'id':'b','name':'B','value':'Beta/2'}],
          'services':{'browser':{'rotation':'round_robin','profiles':['a','b']}}}
    assert client.post('/api/admin/user-agents',json=data).status_code==200
    values=[resolve('browser') for _ in range(4)]
    assert values[0]!=values[1] and values[0]==values[2]
    doc=client.get('/api/admin/user-agents').json()
    save={k:doc[k] for k in ('revision','global_value','profiles','services')}
    save['profiles']=[p for p in save['profiles'] if p['id']!='a']
    assert client.post('/api/admin/user-agents',json=save).status_code==422
    save['services']={}
    assert client.post('/api/admin/user-agents',json=save).status_code==200
    assert resolve('browser')=='Global/1'
    save['revision']+=1
    save['global_value']=None
    assert client.post('/api/admin/user-agents',json=save).status_code==200
    assert resolve('browser')==settings().user_agent_default


def test_rotation_guards(monkeypatch):
    with pytest.raises(ValidationError):
        Document(services={'browser':{'rotation':'random','profiles':['a']}},profiles=[Profile(id='a',name='A',value='A/1')])
    monkeypatch.setattr(settings(),'user_agent_rotatable_services','ai')
    with pytest.raises(ValidationError):
        Document(services={'ai':{'rotation':'random','profiles':['a']}},profiles=[Profile(id='a',name='A',value='A/1')])
    with pytest.raises(ValueError):
        resolve('invented')


async def test_native_http_header_and_retry_identity(monkeypatch):
    import httpx
    from app.outbound import model_clients
    from pydantic import SecretStr
    captured=[]
    original=httpx.AsyncClient
    async def handle(request):
        captured.append(request)
        return httpx.Response(200,json={'ok':True})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handle),**kwargs))
    async with model_clients([('https://provider.test',SecretStr(''),'model')],trust_env=False,follow_redirects=False) as clients:
        for _ in range(2):
            await clients[0].get('https://provider.test/',headers={'Authorization':'Bearer test'})
    assert len(captured)==2
    assert captured[0].headers['user-agent']==captured[1].headers['user-agent']==settings().user_agent_default
    assert captured[0].headers['authorization']=='Bearer test'
    assert len([k for k,v in captured[0].headers.multi_items() if k.lower()=='user-agent'])==1


async def test_real_http_proxy_header_and_bound_rotation(monkeypatch):
    import asyncio
    import httpx
    from app.egress import egress_proxy
    from app.outbound import Manager
    from test_outbound import configured
    seen=[]
    async def target(reader,writer):
        seen.append(await reader.readuntil(b'\r\n\r\n'))
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}')
        await writer.drain()
        writer.close()
    server=await asyncio.start_server(target,'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    monkeypatch.setattr(settings(),'ai_provider','local')
    class Policy:
        def check(self,url,**kwargs): return url
        async def resolve(self,url): return ['127.0.0.1']
    try:
        async with egress_proxy(Policy()) as proxy:
            async with httpx.AsyncClient(proxy=proxy,trust_env=False,headers={'User-Agent':resolve('browser')}) as client:
                await client.get(f'http://127.0.0.1:{port}/',headers={'Authorization':'Bearer test'})
        assert b'User-Agent: '+settings().user_agent_default.encode() in seen[0]
        assert seen[0].lower().count(b'user-agent:')==1
        assert b'Authorization: Bearer test' in seen[0]
        m=Manager(configured(),True)
        pinned=m.bind('browser','job')
        assert all(m.select('browser','job').id==pinned for _ in range(3))
        m.release('browser','job')
    finally:
        server.close()
        await server.wait_closed()

def test_migration_roundtrip_and_singleton_constraints(tmp_path):
    import os
    import subprocess
    import sys
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError
    env=dict(os.environ,ADBOT_DATABASE_URL='sqlite:///'+str(tmp_path/'ua-migration.db'))
    for args in [('upgrade','head'),('upgrade','head'),('downgrade','d17c0a000001'),('upgrade','head')]:
        result=subprocess.run([sys.executable,'-m','alembic',*args],capture_output=True,text=True,env=env)
        assert result.returncode==0,result.stderr
    engine=create_engine(env['ADBOT_DATABASE_URL'])
    with engine.begin() as connection:
        assert connection.scalar(text('SELECT count(*) FROM user_agent_config'))==0
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO user_agent_config (id,revision,payload,updated_at) VALUES (2,0,'{}',0)"))
    engine.dispose()


def test_alternate_rotation_strategies(client,monkeypatch):
    from app import user_agents
    from app.outbound import Manager
    from test_outbound import configured
    monkeypatch.setattr(settings(),'content_admin_keys',KEY)
    monkeypatch.setattr(settings(),'user_agent_rotatable_services','browser')
    m=Manager(configured(),True)
    monkeypatch.setattr('app.outbound.manager',lambda:m)
    doc={'revision':0,'profiles':[{'id':'a','name':'A','value':'A/1'}, {'id':'b','name':'B','value':'B/2','enabled':False}],
         'services':{'browser':{'rotation':'proxy_endpoint','profiles':['a','b']}}}
    assert client.post('/api/admin/user-agents',json=doc).status_code==200
    assert resolve('browser',proxy_endpoint='a')=='A/1'
    current=client.get('/api/admin/user-agents').json()
    doc={k:current[k] for k in ('revision','global_value','profiles','services')}
    doc['services']['browser']['rotation']='random'
    assert client.post('/api/admin/user-agents',json=doc).status_code==200
    assert resolve('browser')=='A/1'
    doc['revision']+=1
    doc['services']['browser']['rotation']='scheduled'
    assert client.post('/api/admin/user-agents',json=doc).status_code==200
    assert resolve('browser')=='A/1'
    assert user_agents.read().revision==3

async def test_internal_request_override_transport_guard(monkeypatch):
    import httpx
    from app.outbound import model_clients
    from pydantic import SecretStr
    original=httpx.AsyncClient
    received=[]
    async def handle(request):
        received.append(request.headers['user-agent'])
        return httpx.Response(200)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    monkeypatch.setattr(settings(),'user_agent_allow_request_overrides',True)
    providers=[('https://provider.test',SecretStr(''),'test')]
    with pytest.raises(PermissionError):
        async with model_clients(providers,user_agent_override='Override/1',trust_env=False):
            pass
    async with model_clients(providers,user_agent_override='Override/1',authorized_override=True,trust_env=False) as clients:
        await clients[0].get('https://provider.test/')
    assert received==['Override/1']

def test_disabled_service_and_profile_fallback(client,monkeypatch):
    monkeypatch.setattr(settings(),'content_admin_keys',KEY)
    doc={'revision':0,'global_value':'Global/1','profiles':[{'id':'off','name':'Off','value':'Unused/1','enabled':False}],
         'services':{'ai':{'value':'Custom/1','enabled':False},'ai_local':{'profile':'off'}}}
    assert client.post('/api/admin/user-agents',json=doc).status_code==200
    assert resolve('ai')==resolve('ai_local')=='Global/1'
    result=client.get('/api/admin/user-agents').json()
    assert result['services']['ai']['updated_at']>0
    assert result['profiles'][0]['created_at']>0
