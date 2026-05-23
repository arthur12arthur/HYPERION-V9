"""
HYPERION V9 — Cache local (TTL-based)
Évite les appels répétés aux sources pour la même journée.
"""
import time
from typing import Any, Optional
from utils.logger import get_logger

logger = get_logger(__name__)


class SimpleCache:
    def __init__(self, ttl_seconds: int = 3600):
        self._store: dict = {}
        self.ttl = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        if key in self._store:
            value, expiry = self._store[key]
            if time.time() < expiry:
                return value
            del self._store[key]
        return None

    def set(self, key: str, value: Any):
        self._store[key] = (value, time.time() + self.ttl)
        logger.debug(f"[CACHE] Set: {key}")

    def clear(self):
        self._store.clear()


# Cache 1h pour les données de la journée
daily_cache = SimpleCache(ttl_seconds=3600)
