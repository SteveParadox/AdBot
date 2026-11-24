// Bounded, payload-free diagnostics. No tokens, query strings or resource IDs.
const counters: Record<string, number> = Object.create(null);
export function count(name: string, amount = 1) { counters[name] = (counters[name] || 0) + amount; }
export function gauge(name: string, value: number) { counters[name] = value; }
export function highWater(name: string, value: number) { counters[name] = Math.max(counters[name] || 0, value); }
export function trafficSnapshot(): {timestamp: string; [name: string]: string | number} { return { timestamp: new Date().toISOString(), ...counters }; }
export function resetTraffic() { for (const key of Object.keys(counters)) delete counters[key]; }
