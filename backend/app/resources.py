"""Host pressure sampling without a mandatory platform dependency."""
import os
import threading


def host_sample():
    """Return cumulative (busy,total) CPU ticks and physical memory use percent."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        class Memory(ctypes.Structure):
            _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in
                ('total_physical', 'available_physical', 'total_page', 'available_page',
                 'total_virtual', 'available_virtual', 'available_extended')
            ]
        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise OSError('Memory sampling failed')
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            raise OSError('CPU sampling failed')
        def ticks(value):
            return (value.dwHighDateTime << 32) + value.dwLowDateTime
        total = ticks(kernel) + ticks(user)
        return total - ticks(idle), total, float(memory.load)
    from pathlib import Path
    values = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    total = sum(values)
    idle = values[3] + values[4]
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    used = 100 * (1 - int(memory['MemAvailable'].split()[0]) / int(memory['MemTotal'].split()[0]))
    return total - idle, total, used


class ResourceMonitor:
    def __init__(self):
        self.previous = None

    def sample(self):
        result = {'active_threads': threading.active_count()}
        try:
            busy, total, memory = host_sample()
            result['host_memory_percent'] = memory
            if self.previous and total > self.previous[1]:
                result['host_cpu_percent'] = max(0, min(100, 100 * (busy - self.previous[0]) / (total - self.previous[1])))
            self.previous = busy, total
        except (OSError, ValueError, KeyError, IndexError):
            result['resource_sampling_unavailable'] = True
        return result


def pressured(sample, cfg):
    return cfg.resource_monitoring_enabled and (
        sample.get('host_memory_percent', 0) >= cfg.max_host_memory_percent
        or sample.get('host_cpu_percent', 0) >= cfg.max_host_cpu_percent
    )
