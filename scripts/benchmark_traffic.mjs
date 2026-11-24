import {createServer} from '../frontend/node_modules/vite/dist/node/index.js';
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import {writeFileSync,mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve,join} from 'node:path';
const output=process.argv[2] || 'docs/traffic-optimization/benchmark.json';
const server=await createServer({root:resolve(process.env.BENCHMARK_FRONTEND_ROOT || 'frontend'),cacheDir:mkdtempSync(join(tmpdir(),'adbot-traffic-vite-')),server:{host:'127.0.0.1',port:15174,strictPort:true}});
await server.listen();
const browser=await chromium.launch({headless:true});
const results={commit:process.env.BENCHMARK_COMMIT || 'working-tree',captured_at:new Date().toISOString(),method:'Actual React app in Chromium, mocked authenticated API and deterministic 60-second browser clock. HTTP counts include initial reads; stream opens counted separately. Not production latency or CPU measurements.',scenarios:{}};
try {
for(const scenario of ['idle','active-task','unrelated-task-in-extraction']) {
 const page=await browser.newPage();let bytes=0;
 const task={id:'task-1',website_id:'site-1',job_type:'agent',status:'running',pages_visited:0,created_at:1,started_at:1,completed_at:null,error_message:null,priority:0,depends_on:null,objective:'Benchmark research task',mode:'supervised',options:{max_steps:500,max_tokens:60000},result:{},memory:{},pending_step_id:null,prompt_tokens:0,completion_tokens:0,model_calls:0,model_latency_ms:0};
 await page.clock.install();
 await page.addInitScript(()=>{
  sessionStorage.setItem('adbot-token','benchmark-fixture-only');
  const native=window.fetch.bind(window),streams=new Set();
  window.__traffic={requests:[],streams:0,emit(events){for(const s of streams)s.enqueue(new TextEncoder().encode(events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join('')));}};
  window.fetch=(url,options)=>{
   const path=String(url);window.__traffic.requests.push(path);
   if(path.includes('/api/events') || /\/api\/jobs\/[^/]+\/events/.test(path)){
    window.__traffic.streams++;
    return Promise.resolve(new Response(new ReadableStream({start(controller){streams.add(controller);controller.enqueue(new TextEncoder().encode('data: {"id":0,"event_type":"sync","details":{"reconcile":false},"change_cursor":0}\n\n'));options?.signal?.addEventListener('abort',()=>{streams.delete(controller);controller.close();},{once:true});},cancel(){}}),{headers:{'Content-Type':'text/event-stream'}}));
   }
   return native(url,options);
  };
 });
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  let result={items:[],total:0};
  if(path==='/api/agent/tasks')result={items:[task],total:1};
  else if(path==='/api/agent/tasks/task-1')result=task;
  else if(path==='/api/agent/config')result={max_steps:500,max_tokens:60000,configured:true,provider:'fixture',model:'fixture'};
  else if(path==='/api/websites')result={items:[{id:'site-1',name:'Fixture',base_url:'https://example.org',allowed_domains:['example.org'],configuration:{}}],total:1};
  else if(path==='/api/analytics/overview')result={websites:1,jobs:1,pages:0,average_ms:0,failure_rate:0,statuses:{running:1},daily_pages:[],http_statuses:[],scheduled_jobs:0,scheduled_success_rate:null};
  else if(path==='/api/extraction/datasets')result={items:[{id:'dataset-1',website_id:'site-1',schema_id:'schema-1',name:'Dataset',version:1,options:{}}],total:1};
  const body=JSON.stringify(result);bytes+=Buffer.byteLength(body);await route.fulfill({body,contentType:'application/json'});
 });
 await page.goto('http://127.0.0.1:15174',{waitUntil:'domcontentloaded',timeout:90000});
 await page.getByRole('heading',{name:'A clearer view of your web.'}).waitFor({timeout:90000});
 for(let tick=0;tick<5;tick++){await page.clock.runFor(1);await new Promise(resolve=>setTimeout(resolve,20));}
 if(scenario==='active-task'){
  await page.getByRole('button',{name:'AI Agent',exact:true}).click();
  await page.getByRole('button',{name:'Inspect task'}).click();
  await page.getByRole('heading',{name:'Benchmark research task'}).waitFor();
 } else if(scenario==='unrelated-task-in-extraction'){
  await page.getByRole('button',{name:'Data Extraction',exact:true}).click();
  await page.getByLabel('Explore dataset').waitFor();
 }
 await new Promise(r=>setTimeout(r,100));
 let id=1;
 for(let second=1;second<=60;second++){
  await page.clock.runFor(1000);
  if(scenario!=='idle'){
   const events=['agent_observed','agent_decision','agent_action_completed'].map(event_type=>({id:id++,job_id:'task-1',event_type,message:'progress',timestamp:Date.now()/1000,details:{step_id:second},resource:{job:task}}));
   await page.evaluate(events=>window.__traffic.emit(events),events);
  } else if(second%10===0) await page.evaluate(()=>window.__traffic.emit([]));
  await new Promise(r=>setTimeout(r,15));
 }
 await page.clock.runFor(2100);await new Promise(r=>setTimeout(r,100));
 const data=await page.evaluate(()=>({requests:window.__traffic.requests,stream_opens:window.__traffic.streams}));
 const counts={};for(const url of data.requests){const endpoint=url.split('?')[0];counts[endpoint]=(counts[endpoint]||0)+1;}
 const streamPaths=url=>url==='/api/events'||/\/api\/jobs\/[^/]+\/events/.test(url);
 results.scenarios[scenario]={duration_virtual_seconds:62.1,http_requests:data.requests.filter(url=>!streamPaths(url)).length,stream_opens:data.stream_opens,json_response_bytes:bytes,requests_by_endpoint:counts};
 await page.close();
}
writeFileSync(output,JSON.stringify(results,null,2)+'\n');console.log(JSON.stringify(results,null,2));
} finally {await browser.close();await server.close();}
