"""Reproducible SQLite/TestClient read benchmark; never uses the user's database."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor

parser = argparse.ArgumentParser()
parser.add_argument('--source', default='backend')
parser.add_argument('--output', required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(args.source).resolve()))
temporary = Path(tempfile.mkdtemp(prefix='adbot-traffic-benchmark-'))
keys = [f'benchmark-owner-{index}-fixture-only-00000000' for index in range(4)]
os.environ.update({
    'ADBOT_DATABASE_URL': 'sqlite:///' + (temporary / 'benchmark.db').as_posix(),
    'ADBOT_API_KEYS': ','.join(keys), 'ADBOT_REDIS_URL': '', 'ADBOT_FIXTURE_MODE': 'true',
    'ADBOT_AI_PROVIDER': 'disabled', 'ADBOT_AI_PROVIDER_ORDER': ' ', 'ADBOT_AI_FALLBACK_PROVIDER': 'disabled', 'ADBOT_ENVIRONMENT': 'development',
    'ADBOT_RATE_PER_MINUTE': '10000', 'ADBOT_OUTBOUND_PROXY_ENABLED': 'false',
})
from fastapi.testclient import TestClient
from sqlalchemy import event
from app.db import Base, engine, Website, Job, AgentTask, transaction
from app.main import app
from app.schemas import WebsiteInput

logging.disable(logging.CRITICAL)
Base.metadata.create_all(engine)
owned_ids = {}
with transaction() as session:
    for index, key in enumerate(keys):
        owner = hashlib.sha256(key.encode()).hexdigest()
        definition = WebsiteInput(name=f'Fixture {index}', base_url='http://127.0.0.1:8765/', allowed_domains=['127.0.0.1'], authorized=True)
        site = Website(owner=owner, **definition.model_dump(exclude={'authorized'}))
        session.add(site); session.flush()
        owned_ids[key] = set()
        for number in range(25):
            job = Job(owner=owner,website_id=site.id,job_type='agent',status='queued',snapshot={'configuration':site.configuration})
            session.add(job); session.flush(); owned_ids[key].add(job.id)
            session.add(AgentTask(job_id=job.id,objective=f'Fixture task {number}',mode='supervised',options={'max_steps':15,'max_tokens':60000},memory={}))

queries = []
def count(*_args): queries.append(1)
event.listen(engine, 'before_cursor_execute', count)
client = TestClient(app)
def read(key):
    response = client.get('/api/agent/tasks?limit=25',headers={'Authorization':'Bearer '+key})
    assert response.status_code == 200, response.text
    assert {row['id'] for row in response.json()['items']} == owned_ids[key]
    return response
# Warm up statement compilation and thread dispatch before sampling.
read(keys[0]); queries.clear()
tracemalloc.start(); cpu_start = time.process_time(); latencies = []; bytes_received = 0
for _ in range(50):
    start = time.perf_counter(); response = read(keys[0]); latencies.append((time.perf_counter()-start)*1000)
    bytes_received += len(response.content)
cpu_ms = (time.process_time()-cpu_start)*1000
_, peak_bytes = tracemalloc.get_traced_memory(); tracemalloc.stop()
sequential_queries = len(queries); queries.clear()
start = time.perf_counter()
with ThreadPoolExecutor(max_workers=4) as workers:
    responses = list(workers.map(read, keys*10))
concurrent_ms = (time.perf_counter()-start)*1000
ordered = sorted(latencies)
result = {
    'captured_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
    'method': 'Isolated temporary SQLite, 4 owners x 25 tasks; 50 sequential warm GETs and 40 GETs across four threads. TestClient latency includes response validation and JSON decoding. CPU is this Python process, memory is tracemalloc peak during sequential reads, not system RSS.',
    'sequential_requests':50,'sql_queries':sequential_queries,'sql_queries_per_request':sequential_queries/50,
    'response_bytes':bytes_received,'api_latency_ms':{f'p{p}':round(ordered[int((len(ordered)-1)*p/100)],3) for p in [50,95,99]},
    'process_cpu_ms':round(cpu_ms,3),'python_heap_peak_bytes':peak_bytes,
    'concurrent_requests':len(responses),'concurrent_wall_ms':round(concurrent_ms,3),'concurrent_sql_queries':len(queries),
    'authorization_isolation':'all four owner-specific response ID sets verified',
}
Path(args.output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8'); print(json.dumps(result,indent=2))
client.close(); engine.dispose()
