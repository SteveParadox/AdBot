import {test,expect,type Page} from '@playwright/test';
import {defaults} from '../src/api';

async function fixture(page: Page, token='traffic-fixture-owner-000000000000000000', holdSync=false) {
 const job={id:'task-1',website_id:'site-1',job_type:'agent',status:'running',pages_visited:0,created_at:1,started_at:1,completed_at:null,error_message:null,priority:0,depends_on:null,objective:'Track fixture task',mode:'supervised',options:{max_steps:100,max_tokens:60000},result:{},memory:{},pending_step_id:null,prompt_tokens:0,completion_tokens:0,model_calls:0,model_latency_ms:0};
 const reads:string[]=[];
 await page.clock.install();
 await page.addInitScript(({token,holdSync})=>{
  sessionStorage.setItem('adbot-token',token);
  const Channel=window.BroadcastChannel;
  if(Channel) window.BroadcastChannel=class extends Channel {constructor(name:string){super(name);(window as any).__channels=((window as any).__channels||0)+1;}};
  const native=window.fetch.bind(window); let active:ReadableStreamDefaultController<Uint8Array>|undefined;
  const state={opens:0,active:0,offline:false,unauthorized:false,headers:[] as Record<string,string>[],emit(events:unknown[]){active?.enqueue(new TextEncoder().encode(events.map(event=>'data: '+JSON.stringify(event)+'\n\n').join('')));},fail(){active?.error(new Error('fixture connection lost'));active=undefined;},visibility(hidden:boolean){Object.defineProperty(document,'hidden',{configurable:true,value:hidden});Object.defineProperty(document,'visibilityState',{configurable:true,value:hidden?'hidden':'visible'});document.dispatchEvent(new Event('visibilitychange',{bubbles:true}));}};
  (window as any).__stream=state;
  setInterval(()=>active?.enqueue(new TextEncoder().encode(': heartbeat\n\n')),10000);
  window.fetch=(input,options)=>{
   if(String(input)==='/api/events'){
    state.opens++;state.headers.push(options?.headers as Record<string,string>);
    if(state.offline)return Promise.reject(new Error('fixture offline'));
    if(state.unauthorized)return Promise.resolve(new Response('',{status:401}));
    return Promise.resolve(new Response(new ReadableStream({start(controller){state.active++;active=controller;if(!holdSync)controller.enqueue(new TextEncoder().encode('data: {"id":0,"event_type":"sync","details":{"reconcile":false},"change_cursor":0}\n\n'));options?.signal?.addEventListener('abort',()=>{state.active--;active=undefined;try{controller.close();}catch{}},{once:true});}}),{headers:{'Content-Type':'text/event-stream'}}));
   }
   return native(input,options);
  };
 },{token,holdSync});
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(route.request().method()==='GET')reads.push(path);
  let result:unknown={items:[],total:0};
  if(path==='/api/websites')result={items:[{id:'site-1',name:'Fixture',base_url:'https://example.org',allowed_domains:['example.org'],configuration:defaults},{id:'site-2',name:'Second fixture',base_url:'https://second.example.org',allowed_domains:['example.org'],configuration:defaults}],total:2};
  else if(path==='/api/analytics/overview')result={websites:1,jobs:1,pages:0,average_ms:0,failure_rate:0,statuses:{running:1},daily_pages:[],http_statuses:[],scheduled_jobs:0,scheduled_success_rate:null};
  else if(path==='/api/extraction/datasets')result={items:[{id:'dataset-1',name:'First dataset',website_id:'site-1'},{id:'dataset-2',name:'Second dataset',website_id:'site-2'}],total:2};
  else if(path==='/api/agent/config')result={max_steps:100,max_tokens:60000,configured:true,provider:'fixture',model:'fixture'};
  else if(path==='/api/agent/tasks')result={items:[job],total:1};
  else if(path==='/api/agent/tasks/task-1')result=job;
  await route.fulfill({json:result,headers:{'X-Request-ID':'a'.repeat(32)}});
 });
 await page.goto('/');
 await page.getByRole('heading',{name:'A clearer view of your web.'}).waitFor();
 await expect.poll(async()=>{await page.clock.runFor(1);return page.evaluate(()=>(window as any).__stream.active);}).toBe(1);
 return {reads,job};
}
async function inspect(page:Page){await page.getByRole('button',{name:'AI Agent',exact:true}).click();await page.getByRole('button',{name:'Inspect task'}).click();await page.getByRole('heading',{name:'Track fixture task'}).waitFor();}

test('one Strict Mode stream drives terminal task and step updates without snapshot storms',async({page})=>{
 const {reads,job}=await fixture(page);await inspect(page);
 await expect.poll(()=>reads.filter(path=>path==='/api/agent/tasks/task-1/steps').length).toBe(1);
 const events=Array.from({length:300},(_,index)=>({id:index+1,job_id:job.id,snapshot_batch:true,event_type:index===299?'completed':'agent_action_completed',message:'fixture progress',details:{},timestamp:Date.now()/1000,resource:{job:{...job,status:index===299?'completed':'running'},task:{...job,status:index===299?'completed':'running'},steps:[{id:1,number:1,status:'succeeded',observation:{url:'https://example.org'},decision:{},outcome:{}}]}}));
 const started=Date.now();
 await page.evaluate(events=>(window as any).__stream.emit(events),events);
 await expect(page.getByRole('button',{name:'Stop agent'})).toHaveCount(0);
 await expect(page.getByText('1/100 steps',{exact:true})).toBeVisible();
 await test.info().attach('event-to-ui-latency.json',{body:JSON.stringify({wall_ms:Date.now()-started,events:events.length,method:'Driver-observed synthetic event-to-render wall time, not production latency'}),contentType:'application/json'});
 await page.clock.runFor(65000);
 expect(reads.filter(path=>path==='/api/agent/tasks/task-1')).toHaveLength(1);
 expect(reads.filter(path=>path==='/api/agent/tasks/task-1/steps')).toHaveLength(1);
 expect(await page.evaluate(()=>(window as any).__stream.opens)).toBe(1);
 expect(await page.evaluate(()=>(window as any).__stream.active)).toBe(1);
});

test('agent task activity follows live status and respects reduced motion', async ({ page }) => {
  const { job } = await fixture(page);
  const detail = Promise.withResolvers<void>();
  await page.route('**/api/agent/tasks/task-1', async (route) => {
    await detail.promise;
    await route.fulfill({ json: { ...job, status: 'queued' } });
  }, { times: 1 });

  await page.getByRole('button', { name: 'AI Agent', exact: true }).click();
  await page.getByRole('button', { name: 'Inspect task' }).click();
  const activity = page.locator('.agent-task-activity');
  const spinner = activity.locator('svg');
  const status = await activity.elementHandle();
  try {
    await expect(activity).toHaveText('Loading agent task…');
  } finally {
    detail.resolve();
  }
  await page.getByRole('heading', { name: job.objective }).waitFor();
  await expect(activity).toBeEmpty();

  async function updateStatus(id: number, nextStatus: string) {
    const task = { ...job, status: nextStatus };
    await page.evaluate((event) => (window as any).__stream.emit([event]), {
      id, job_id: job.id, snapshot_batch: true, event_type: nextStatus,
      message: nextStatus, details: {}, resource: { job: task, task },
    });
  }

  await updateStatus(1, 'running');
  await expect(activity).toHaveText('Thinking…');
  expect(await status?.evaluate((element) => element.textContent)).toBe('Thinking…');
  await expect(spinner).toHaveCSS('animation-name', 'spin');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(spinner).toHaveCSS('animation-name', 'none');
  await expect(activity).toHaveText('Thinking…');

  await updateStatus(2, 'waiting_user');
  await expect(activity).toBeEmpty();
  await updateStatus(3, 'running');
  await expect(activity).toHaveText('Thinking…');
  await updateStatus(4, 'completed');
  await expect(activity).toBeEmpty();
  await expect(spinner).toHaveCount(0);
});

test('visibility closes the stream and resumes with its replay cursor',async({page})=>{
 await fixture(page);
 await page.evaluate(()=>{(window as any).__stream.emit([{id:42,event_type:'progress',message:'ok',details:{}}]);});
 await expect.poll(()=>page.evaluate(()=>(window as any).adbotTraffic().events_received)).toBeGreaterThan(1);
 await page.evaluate(()=>(window as any).__stream.visibility(true));
 await page.clock.runFor(60000);
 expect(await page.evaluate(()=>(window as any).__stream.opens)).toBe(1);
 expect(await page.evaluate(()=>(window as any).__stream.active)).toBe(0);
 await page.evaluate(()=>(window as any).__stream.visibility(false));
 await expect.poll(()=>page.evaluate(()=>(window as any).__stream.opens)).toBe(2);
 expect(await page.evaluate(()=>(window as any).__stream.headers.at(-1)['Last-Event-ID'])).toBe('42');
});

test('fallback reads recover during an outage and stop after the stream heals',async({page})=>{
 const {reads}=await fixture(page);await inspect(page);
 await page.evaluate(()=>{(window as any).__stream.offline=true;(window as any).__stream.fail();});
 await page.clock.runFor(35000);
 await expect.poll(()=>reads.filter(path=>path==='/api/agent/tasks/task-1').length).toBeGreaterThan(1);
 expect(reads.filter(path=>path==='/api/agent/config')).toHaveLength(1);
 await page.evaluate(()=>{(window as any).__stream.offline=false;window.dispatchEvent(new Event('online'));});
 await expect.poll(()=>page.evaluate(()=>(window as any).__stream.active)).toBeGreaterThan(0);
 const count=reads.filter(path=>path==='/api/agent/tasks/task-1').length;
 await page.clock.runFor(65000);
 expect(reads.filter(path=>path==='/api/agent/tasks/task-1')).toHaveLength(count);
});

test('expired stream credentials return to login and stop private refreshes',async({page})=>{
 await fixture(page);await inspect(page);
 await page.evaluate(()=>{(window as any).__stream.unauthorized=true;(window as any).__stream.fail();});
 await page.clock.runFor(2000);
 await expect(page.getByLabel('Workspace API key')).toBeVisible();
 const opens=await page.evaluate(()=>(window as any).__stream.opens);
 await page.clock.runFor(65000);
 expect(await page.evaluate(()=>(window as any).__stream.opens)).toBe(opens);
});

test('same-owner tabs share modification notices while another owner stays isolated',async({context})=>{
 const first=await context.newPage(), second=await context.newPage(), other=await context.newPage();
 const a=await fixture(first),b=await fixture(second),c=await fixture(other,'another-traffic-owner-00000000000000000');
 // Wait for the asynchronous channel-name digest to settle in each tab.
 await expect.poll(()=>first.evaluate(()=>(window as any).__channels||0)).toBe(1);
 await expect.poll(()=>second.evaluate(()=>(window as any).__channels||0)).toBe(1);
 await first.evaluate(async()=>{const api=await import('/src/api.ts');await api.api('/workflows','traffic-fixture-owner-000000000000000000','POST',{});});
 await expect.poll(()=>b.reads.filter(path=>path==='/api/workflows').length).toBeGreaterThan(1);
 expect(a.reads.filter(path=>path==='/api/workflows')).toHaveLength(2);
 expect(c.reads.filter(path=>path==='/api/workflows')).toHaveLength(1);
 await Promise.all([first.close(),second.close(),other.close()]);
});


test('a server cursor reset accepts lower event IDs and restores active task state',async({page})=>{
 const {job}=await fixture(page);await inspect(page);
 await page.evaluate(event=>(window as any).__stream.emit([event]),{id:500,job_id:job.id,snapshot_batch:true,event_type:'completed',message:'done',details:{},resource:{job:{...job,status:'completed'},task:{...job,status:'completed'}}});
 await expect(page.getByRole('button',{name:'Stop agent'})).toHaveCount(0);
 await page.evaluate(events=>(window as any).__stream.emit(events),[
  {id:0,event_type:'sync',details:{reconcile:true,reset:true},change_cursor:0},
  {id:1,job_id:job.id,snapshot_batch:true,event_type:'agent_action_completed',message:'restored',details:{},resource:{job,task:{...job,model_calls:99}}},
 ]);
 await expect(page.getByRole('button',{name:'Stop agent'})).toBeVisible();
 await expect(page.getByText(/99 model calls/)).toBeVisible();
});


test('authenticated initial snapshots wait for the stream cursor, avoiding a startup gap',async({page})=>{
 const {reads}=await fixture(page,'traffic-fixture-owner-000000000000000000',true);
 expect(reads.filter(path=>path!=='/api/content')).toHaveLength(0);
 await page.evaluate(()=>(window as any).__stream.emit([{id:0,event_type:'sync',details:{reconcile:false},change_cursor:0}]));
 await expect.poll(()=>reads.includes('/api/websites')).toBe(true);
 await expect.poll(()=>reads.includes('/api/jobs')).toBe(true);
});


test('switching agent targets reuses the shared dataset collection cache',async({page})=>{
 const {reads}=await fixture(page);
 await page.getByRole('button',{name:'AI Agent',exact:true}).click();
 await page.getByLabel('Agent target').selectOption('site-1');
 await page.getByText('Dataset output, priority and dependencies',{exact:true}).click();
 const dataset=page.getByLabel('Structured extraction dataset');
 await expect(dataset.locator('option[value="dataset-1"]')).toHaveCount(1);
 await dataset.selectOption('dataset-1');
 await page.getByLabel('Agent target').selectOption('site-2');
 await expect(dataset.locator('option[value="dataset-2"]')).toHaveCount(1);
 await expect(dataset).toHaveValue('');
 expect(reads.filter(path=>path==='/api/extraction/datasets')).toHaveLength(1);
});
