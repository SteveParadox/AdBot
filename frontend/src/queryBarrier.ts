// Establish the durable event cursor before initial authenticated snapshots.
// Public reads and explicit API actions remain independent of stream availability.
const barriers = new Map<string, {promise: Promise<void>; release: () => void; references: number}>();
export function holdInitialQueries(token: string) {
  let entry = barriers.get(token);
  if (!entry) {
    let release!: () => void;
    const promise = new Promise<void>(resolve => {release = resolve;});
    entry = {promise, release, references: 0}; barriers.set(token, entry);
  }
  entry.references++;
  let disposed = false;
  return {release: entry.release, dispose() {
    if (disposed) return;
    disposed = true; entry!.references--;
    if (!entry!.references) {entry!.release(); if (barriers.get(token) === entry) barriers.delete(token);}
  }};
}
export function waitForInitialCursor(token: string, signal: AbortSignal) {
  const entry = barriers.get(token);
  if (!entry) return Promise.resolve();
  return new Promise<void>((resolve, reject) => {
    const abort = () => {signal.removeEventListener("abort", abort); reject(new DOMException("Request cancelled", "AbortError"));};
    if (signal.aborted) {abort(); return;}
    signal.addEventListener("abort", abort, {once: true});
    void entry.promise.then(() => {signal.removeEventListener("abort", abort); resolve();});
  });
}
