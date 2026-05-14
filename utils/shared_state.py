import threading
from threading import Lock
from collections import defaultdict, deque

MAX_POINTS_PER_TAG = 10_000

# This is now the single source of truth for the whole app
tag_data      = defaultdict(lambda: deque(maxlen=MAX_POINTS_PER_TAG))
active_tags   = set()
state_lock    = threading.Lock()