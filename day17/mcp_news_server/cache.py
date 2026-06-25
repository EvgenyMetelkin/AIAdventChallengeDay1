import time
import hashlib
import json
from threading import Lock
from typing import Any, Dict, Optional, Tuple


class TTLCache:
    """Простой in-memory кэш с TTL и ограничением размера."""

    def __init__(self, max_size: int = 100, ttl_seconds: int = 3600):
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = Lock()
        self._max_size = max_size
        self._ttl = ttl_seconds

    def _make_key(self, *args, **kwargs) -> str:
        raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            timestamp, value = entry
            if time.time() - timestamp > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._store) >= self._max_size:
                oldest = min(self._store.items(), key=lambda x: x[1][0])
                del self._store[oldest[0]]
            self._store[key] = (time.time(), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
