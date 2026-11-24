import {expect,it,vi} from "vitest";
import {holdInitialQueries,waitForInitialCursor} from "./queryBarrier";

it("shares a cursor barrier and releases pending reads when fallback is needed",async()=>{
 const first=holdInitialQueries("owner"),second=holdInitialQueries("owner");
 const resolved=vi.fn();
 const waiting=waitForInitialCursor("owner",new AbortController().signal).then(resolved);
 first.dispose();await Promise.resolve();expect(resolved).not.toHaveBeenCalled();
 second.release();await waiting;expect(resolved).toHaveBeenCalledTimes(1);second.dispose();
});
it("cancels an obsolete query before its initial snapshot is dispatched",async()=>{
 const barrier=holdInitialQueries("cancel-owner"),controller=new AbortController();
 const waiting=waitForInitialCursor("cancel-owner",controller.signal);
 controller.abort();await expect(waiting).rejects.toHaveProperty("name","AbortError");barrier.dispose();
});
