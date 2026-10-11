from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Generic, Hashable, TypeVar


T = TypeVar("T")


@dataclass(slots=True)
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    """Small thread-safe LRU/TTL cache; cached frames are copied on access."""

    def __init__(self, maxsize: int = 128, ttl_seconds: int = 300) -> None:
        if maxsize < 1:
            raise ValueError("maxsize는 1 이상이어야 합니다.")
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._items: OrderedDict[Hashable, _Entry[T]] = OrderedDict()
        self._lock = RLock()

    @staticmethod
    def _copy(value: T) -> T:
        copier = getattr(value, "copy", None)
        return copier(deep=True) if callable(copier) else deepcopy(value)

    def get(self, key: Hashable) -> T | None:
        now = monotonic()
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            if entry.expires_at < now:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return self._copy(entry.value)

    def set(self, key: Hashable, value: T) -> None:
        expires_at = monotonic() + max(0, self.ttl_seconds)
        with self._lock:
            self._items[key] = _Entry(self._copy(value), expires_at)
            self._items.move_to_end(key)
            while len(self._items) > self.maxsize:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
