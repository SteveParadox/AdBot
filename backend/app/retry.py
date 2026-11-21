"""Retry-After is a minimum wait; jitter never shortens the provider's delay."""
import math
import random
import time
from email.utils import parsedate_to_datetime


def retry_delay(value, attempt):
    minimum = 0
    if value:
        try:
            minimum = float(value)
        except (TypeError, ValueError):
            try:
                minimum = parsedate_to_datetime(value).timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                minimum = 0
    if not math.isfinite(minimum):
        minimum = 0
    return max(2 ** attempt, minimum) + random.uniform(0, .25)
