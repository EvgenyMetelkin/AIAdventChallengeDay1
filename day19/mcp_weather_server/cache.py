import json
import hashlib
import os
import time
from threading import Lock
from typing import Any, Optional


class FileCache:
    """Файловый кэш с TTL, потокобезопасный."""

    def __init__(self, cache_dir: str = "./cache", ttl_seconds: int = 300):
        self._cache_dir = cache_dir
        self._ttl = ttl_seconds
        self._lock = Lock()
        os.makedirs(self._cache_dir, exist_ok=True)

    def _make_key(self, *args, **kwargs) -> str:
        raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _path_for(self, key: str) -> str:
        return os.path.join(self._cache_dir, f"{key}.json")

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            path = self._path_for(key)
            if not os.path.isfile(path):
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    entry = json.load(f)
            except (json.JSONDecodeError, OSError):
                os.remove(path)
                return None
            expires_at = entry.get("expires_at", 0)
            if time.time() >= expires_at:
                try:
                    os.remove(path)
                except OSError:
                    pass
                return None
            return entry.get("data")

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            entry = {
                "data": value,
                "expires_at": time.time() + self._ttl,
            }
            path = self._path_for(key)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(entry, f, ensure_ascii=False)
            except OSError:
                pass
