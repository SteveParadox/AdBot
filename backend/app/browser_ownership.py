"""Exclusive in-process ownership of mutable browser resources.

Inspired by Browser Use's Agent.run ownership guard; independently implemented
for Playwright runners. Database leases remain the cross-process job authority.
"""

from contextlib import contextmanager
from threading import Lock


_lock = Lock()
_active = {}  # id(resource) -> (resource, owner); retain identity until release


@contextmanager
def exclusive_owner(resource, owner, label):
    """Reject overlap, including reentry, without touching the existing owner's state."""
    key = id(resource)
    with _lock:
        if key in _active:
            raise RuntimeError(f"{label} is already in use; each concurrent task requires its own runner and browser")
        _active[key] = (resource, owner)
    try:
        yield
    finally:
        with _lock:
            del _active[key]
