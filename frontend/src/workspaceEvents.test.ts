import { resetTraffic, trafficSnapshot } from "./traffic";
import { afterEach, expect, it, vi } from "vitest";
import { QueryObserver } from "@tanstack/react-query";
import { createQueryClient, mutationKeys } from "./queryClient";
import { createWorkspaceEventHandler } from "./workspaceEvents";
import type { Event, Job } from "./api";

afterEach(() => vi.useRealTimers());
const job = {id:"one", status:"running", job_type:"agent"} as Job;
const event = (id: number, type = "agent_action_completed", fields: Partial<Event> = {}): Event => ({
  id, job_id:"one", snapshot_batch:true, event_type:type, message:"progress", details:{}, timestamp:1,
  resource:{job, task:{...job, model_calls:id}, steps:[{id:1,number:1,status:"succeeded"}]}, ...fields,
});

it("patches a burst of task/step progress without fetching collections or unrelated datasets", async () => {
  vi.useFakeTimers(); const client = createQueryClient();
  for (const key of [["agent-task","one","a"],["job","one","a"]]) client.setQueryData(key, job);
  client.setQueryData(["agent-task","one","b"], {...job, model_calls:0});
  client.setQueryData(["agent-steps","one","a"], {items:[],total:0});
  client.setQueryData(["agent-tasks","a",0], {items:[job],total:1});
  client.setQueryData(["logs","one","a"], {items:[],total:0});
  const invalidate = vi.spyOn(client,"invalidateQueries");
  const handler = createWorkspaceEventHandler(client,"a");
  handler.receive(Array.from({length:300},(_,index)=>event(index+1)));
  await vi.advanceTimersByTimeAsync(2000);
  expect(invalidate).not.toHaveBeenCalled();
  expect(client.getQueryData(["agent-task","one","a"])).toMatchObject({model_calls:300});
  expect(client.getQueryData(["agent-task","one","b"])).toMatchObject({model_calls:0});
  expect(client.getQueryData<{items:unknown[]}>(["logs","one","a"])!.items).toHaveLength(200);
  expect(client.getQueryData<{items:unknown[]}>(["agent-steps","one","a"])!.items).toHaveLength(1);
  handler.dispose(); client.clear();
});

it("ignores older patches and updates membership of status-filtered job pages", async () => {
  const client = createQueryClient();
  client.setQueryData(["agent-task","one","a"], job);
  client.setQueryData(["jobs","a",0,"running"], {items:[job],total:1});
  const handler = createWorkspaceEventHandler(client,"a");
  handler.receive([event(3,"completed",{resource:{job:{...job,status:"completed"},task:{...job,status:"completed"}}}),event(2)]);
  await Promise.resolve();
  expect(client.getQueryData(["agent-task","one","a"])).toMatchObject({status:"completed"});
  expect(client.getQueryData(["jobs","a",0,"running"])).toEqual({items:[],total:0});
  handler.dispose(); client.clear();
});

it("coalesces extraction writes by dataset and flushes terminal changes immediately", async () => {
  vi.useFakeTimers(); const client = createQueryClient();
  const invalidate = vi.spyOn(client,"invalidateQueries");
  const handler = createWorkspaceEventHandler(client,"a");
  handler.receive(Array.from({length:100},(_,index)=>event(index+1,"records_extracted",{resource:{job,dataset_id:"dataset"}})));
  expect(invalidate).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1000);
  expect(invalidate).toHaveBeenCalledTimes(4);
  const keys = invalidate.mock.calls.map(call=>call[0]!.queryKey);
  expect(keys).toContainEqual(["extraction","a","records","dataset"]);
  expect(keys).not.toContainEqual(["agent-config"]);
  expect(keys).not.toContainEqual(["jobs","a"]);
  handler.receive([event(101,"completed",{resource:{job:{...job,job_type:"export"},dataset_id:"dataset"}})]);
  expect(invalidate).toHaveBeenCalledTimes(5);
  handler.dispose(); client.clear();
});

it("reconciles after a reconnect, but an initial sync does not refetch warm queries", async () => {
  const client = createQueryClient(), queryFn = vi.fn(async()=>job);
  const observer = new QueryObserver(client,{queryKey:["agent-task","one","a"],queryFn,initialData:job});
  const unsubscribe = observer.subscribe(()=>undefined);
  const handler = createWorkspaceEventHandler(client,"a");
  handler.receive([{id:0,message:"sync",timestamp:0,event_type:"sync",details:{reconcile:false}} as Event]);
  expect(queryFn).not.toHaveBeenCalled();
  handler.receive([{id:0,message:"sync",timestamp:0,event_type:"sync",details:{reconcile:true}} as Event]);
  await Promise.resolve(); expect(queryFn).toHaveBeenCalledTimes(1);
  handler.dispose(); unsubscribe(); client.clear();
});

it("keeps a newer streamed snapshot when an old GET resolves late", async () => {
  const client = createQueryClient();
  let resolve!: (value: unknown) => void;
  const observer = new QueryObserver(client,{queryKey:["agent-task","one","a"],queryFn:()=>new Promise(done=>{resolve=done;})});
  const unsubscribe = observer.subscribe(()=>undefined);
  const handler = createWorkspaceEventHandler(client,"a");
  handler.receive([event(2,"completed",{resource:{job:{...job,status:"completed"},task:{...job,status:"completed"}}})]);
  resolve(job);
  await new Promise(done=>setTimeout(done,0));
  expect(client.getQueryData(["agent-task","one","a"])).toMatchObject({status:"completed"});
  handler.dispose(); unsubscribe(); client.clear();
});

it("cancels queued invalidations when the workspace unmounts", async () => {
  vi.useFakeTimers(); const client = createQueryClient();
  const invalidate = vi.spyOn(client,"invalidateQueries");
  const handler = createWorkspaceEventHandler(client,"a");
  handler.receive([event(1,"resources_changed",{details:{paths:["/workflows/one"]}})]);
  handler.dispose(); await vi.advanceTimersByTimeAsync(2000);
  expect(invalidate).not.toHaveBeenCalled(); client.clear();
});


it("acknowledges local modification notifications without hiding a different writer's update", async () => {
  vi.useFakeTimers(); const client = createQueryClient();
  const invalidate = vi.spyOn(client,"invalidateQueries");
  const handler = createWorkspaceEventHandler(client,"a");
  const requestId = "a".repeat(32); handler.acknowledge(requestId);
  handler.receive([event(1,"resources_changed",{details:{changes:[{path:"/workflows/one",request_id:requestId}]}})]);
  await vi.advanceTimersByTimeAsync(1001); expect(invalidate).not.toHaveBeenCalled();
  handler.receive([event(1,"resources_changed",{details:{changes:[{path:"/workflows/one",request_id:"b".repeat(32)}]}})]);
  await vi.advanceTimersByTimeAsync(1001);
  expect(invalidate).toHaveBeenCalledWith({queryKey:["workflows","a"]},{cancelRefetch:false});
  handler.dispose(); client.clear();
});


it("accepts new lower sequence numbers after a server cursor reset and clears future logs", async () => {
  const client = createQueryClient();
  client.setQueryData(["agent-task","one","a"], job);
  client.setQueryData(["logs","one","a"], {items:[],total:0});
  const handler = createWorkspaceEventHandler(client,"a");
  handler.receive([event(500,"completed",{resource:{job:{...job,status:"completed"},task:{...job,status:"completed"}}})]);
  handler.receive([{id:0,message:"reset",timestamp:0,event_type:"sync",details:{reconcile:true,reset:true}}]);
  handler.receive([event(1,"agent_action_completed",{resource:{job,task:{...job,model_calls:99}}})]);
  expect(client.getQueryData(["agent-task","one","a"])).toMatchObject({status:"running",model_calls:99});
  expect(client.getQueryData<{items:Event[]}>(["logs","one","a"])!.items.map(item=>item.id)).toEqual([1]);
  handler.dispose(); client.clear();
});

it("invalidates parent deletion dependents and cached details only in the owning workspace", () => {
  const client = createQueryClient();
  client.setQueryData(["agent-task","one","a"], {...job,website_id:"site"});
  client.setQueryData(["agent-task","one","b"], {...job,website_id:"site"});
  const keys = mutationKeys("/websites/site/deleted","a",client);
  expect(keys).toContainEqual(["agent-task","one","a"]);
  expect(keys).not.toContainEqual(["agent-task","one","b"]);
  expect(keys).toContainEqual(["workflows","a"]);
  expect(keys).toContainEqual(["extraction","a","datasets"]);
  expect(keys).not.toContainEqual(["agent-config","a"]);
  client.clear();
});

it("bounds invalidation bursts and reconciles owned queries on overflow", async () => {
  vi.useFakeTimers(); const client = createQueryClient();
  const invalidate = vi.spyOn(client,"invalidateQueries");
  const handler = createWorkspaceEventHandler(client,"a");
  resetTraffic();
  handler.receive(Array.from({length:500},(_,id)=>event(id+1,"navigation_completed",{job_id:`job-${id}`,resource:undefined})));
  expect(trafficSnapshot().event_queue_depth).toBe(256);
  await vi.advanceTimersByTimeAsync(1001);
  expect(invalidate).toHaveBeenCalledTimes(1);
  expect(trafficSnapshot().event_queue_depth).toBe(0);
  expect(trafficSnapshot().event_queue_peak_depth).toBe(256);
  expect(invalidate.mock.calls[0][0]!.predicate).toBeTypeOf("function");
  handler.dispose(); client.clear();
});


it("reconciles mounted extraction results from a legacy payload without refreshing configuration", async () => {
  vi.useFakeTimers(); const client=createQueryClient(), fetch=vi.fn(async()=>({items:[],total:0}));
  const observer=new QueryObserver(client,{queryKey:["extraction","a","records","dataset",0],queryFn:fetch,initialData:{items:[],total:0}});
  const unsubscribe=observer.subscribe(()=>undefined);
  const invalidate=vi.spyOn(client,"invalidateQueries"),handler=createWorkspaceEventHandler(client,"a");
  handler.receive([event(1,"records_extracted",{snapshot_batch:undefined,resource:undefined})]);
  await vi.advanceTimersByTimeAsync(1001);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(invalidate.mock.calls.some(call=>call[0]?.queryKey?.[0]==="agent-config")).toBe(false);
  handler.dispose();unsubscribe();client.clear();
});


it("routes oversized terminal snapshots using their small job and dataset hints", () => {
  const client=createQueryClient(),invalidate=vi.spyOn(client,"invalidateQueries");
  const handler=createWorkspaceEventHandler(client,"a");
  handler.receive([event(1,"completed",{snapshot_batch:false,resource:undefined,details:{job_type:"agent",dataset_id:"dataset"}})]);
  const keys=invalidate.mock.calls.map(call=>call[0]?.queryKey);
  expect(keys).toContainEqual(["agent-memories","a"]);
  expect(keys).toContainEqual(["extraction","a","records","dataset"]);
  expect(keys).not.toContainEqual(["extraction","a","schemas"]);
  handler.dispose();client.clear();
});
