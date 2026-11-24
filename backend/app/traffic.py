"""Bounded process-local operational counters, without URLs, keys or payloads."""
import contextvars
import time
from collections import OrderedDict

request_counters = contextvars.ContextVar("request_counters", default=None)
_workspaces = OrderedDict()
_active_streams = {}


def record(owner, route, status, duration_ms, sql_count):
    if not owner:
        return
    metrics = _workspaces.setdefault(owner, {"requests": 0, "sql_queries": 0, "errors": 0, "duration_ms": 0, "endpoints": {}, "samples_ms": [], "started_at": time.time()})
    _workspaces.move_to_end(owner)
    while len(_workspaces) > 512:
        _workspaces.popitem(last=False)
    metrics["requests"] += 1
    metrics["errors"] += int(status >= 400)
    metrics["sql_queries"] += sql_count
    metrics["duration_ms"] += duration_ms
    metrics["samples_ms"] = (metrics["samples_ms"] + [round(duration_ms, 3)])[-128:]
    metrics["endpoints"][route] = metrics["endpoints"].get(route, 0) + 1


def stream_opened(owner):
    _active_streams[owner] = _active_streams.get(owner, 0) + 1


def stream_closed(owner):
    value = _active_streams.get(owner, 0) - 1
    if value <= 0:
        _active_streams.pop(owner, None)
    else:
        _active_streams[owner] = value


def snapshot(owner):
    values = _workspaces.get(owner, {})
    samples = sorted(values.get("samples_ms", []))
    quantiles = {f"p{percent}": samples[min(len(samples) - 1, int((len(samples) - 1) * percent / 100))] if samples else None
                 for percent in (50, 95, 99)}
    return {"timestamp": time.time(), "scope": "workspace-in-this-api-process",
            **{key: value for key, value in values.items() if key != "samples_ms"},
            "active_streams": _active_streams.get(owner, 0),
            "latency_ms_last_128": quantiles,
            "requests_per_second": values.get("requests", 0) / max(1, time.time() - values.get("started_at", time.time()))}
