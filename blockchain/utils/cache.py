import time
from typing import Any, Callable, Dict, Tuple


class TTLCache:
    """Simple in-memory TTL cache for lightweight hot-path lookups.

    Not process-safe and resets on process restart, which is fine for our use cases.
    """

    def __init__(self):
        self._store: Dict[Tuple[Any, ...], Tuple[float, Any]] = {}

    def get(self, key: Tuple[Any, ...]) -> Any:
        entry = self._store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            # Expired
            try:
                del self._store[key]
            except KeyError:
                pass
            return None
        return value

    def set(self, key: Tuple[Any, ...], value: Any, ttl_seconds: float) -> None:
        self._store[key] = (time.time() + ttl_seconds, value)


# Module-level singleton cache
ttl_cache = TTLCache()

