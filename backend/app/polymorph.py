import random


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/124.0.0.0 Safari/537.36",
]


VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
    {"width": 1600, "height": 900},
    {"width": 1680, "height": 1050},
]


def get_random_user_agent():
    return random.choice(USER_AGENTS)


def get_random_viewport():
    v = random.choice(VIEWPORTS)
    return {"width": v["width"], "height": v["height"]}


def get_random_wait_time(min_seconds=0.05, max_seconds=0.2):
    if min_seconds is None and max_seconds is None:
        min_seconds, max_seconds = 0.05, 0.2
    if min_seconds is None:
        min_seconds = 0.0
    if max_seconds is None:
        max_seconds = min_seconds * 2.0 if min_seconds > 0 else 0.5
    if max_seconds < min_seconds:
        min_seconds, max_seconds = max_seconds, min_seconds
    return random.uniform(min_seconds, max_seconds)


def get_random_scroll_amount(min_amount=100, max_amount=400):
    if min_amount is None and max_amount is None:
        min_amount, max_amount = 100, 400
    if min_amount is None:
        min_amount = 50
    if max_amount is None:
        max_amount = int(min_amount) * 4
    if max_amount < min_amount:
        min_amount, max_amount = max_amount, min_amount
    return random.randint(int(min_amount), int(max_amount))


def calculate_retry_delay(attempt, base=1.0, factor=2.0, jitter=True):
    try:
        attempt = int(attempt)
    except Exception:
        attempt = 0
    delay = base * (factor ** attempt)
    if jitter:
        delay = delay * random.uniform(0.8, 1.2)
    return max(0.1, delay)


random_user_agent = get_random_user_agent
random_viewport = get_random_viewport
random_wait = get_random_wait_time
random_delay = get_random_wait_time
get_random_delay = get_random_wait_time
random_scroll = get_random_scroll_amount
get_random_scroll_amount = get_random_scroll_amount
retry_delay = calculate_retry_delay
