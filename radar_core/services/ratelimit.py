"""Rate limiting por reporter_hash (S-16).

Ventana deslizante en memoria. Hashes distintos no se afectan entre sí.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from ..config import get_settings


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def permitir(self, clave: str) -> bool:
        s = get_settings()
        ahora = time.monotonic()
        with self._lock:
            q = self._hits[clave]
            corte = ahora - s.rate_limit_ventana_seg
            while q and q[0] < corte:
                q.popleft()
            if len(q) >= s.rate_limit_max:
                return False
            q.append(ahora)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()
