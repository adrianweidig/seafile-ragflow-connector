from __future__ import annotations

import threading
import time
from collections.abc import Callable


class ReadinessCache[T]:
    def __init__(self, ttl_seconds: float = 5.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._expires_at = 0.0
        self._value: T | None = None

    def get(self, loader: Callable[[], T]) -> T:
        now = time.monotonic()
        with self._lock:
            if self._value is not None and now < self._expires_at:
                return self._value
            self._value = loader()
            self._expires_at = time.monotonic() + self.ttl_seconds
            return self._value
