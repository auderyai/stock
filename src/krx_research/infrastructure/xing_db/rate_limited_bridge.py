from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any


class RateLimitedRawTrBridge:
    """RawTrPort decorator enforcing LS same-TR and rolling-window quotas.

    DLL/codec internals stay in XingBridgeClient/32-bit worker. This adapter owns
    only transport pacing/retry. t8429 follows DevCenter: 1 call/sec and 200 calls/10min.
    """

    _DEFAULT_INTERVAL = 0.25
    _TR_INTERVALS = {"t1516": 1.10, "t1702": 1.10, "t8429": 1.10, "t8451": 0.35}
    _WINDOW_LIMITS = {"t8429": (200, 600.0)}
    _RETRY_DELAYS = (1.25, 2.50, 5.50)
    _EXTERNAL_QUOTA_COOLDOWN = 610.0

    def __init__(self, inner: Any, *, sleep_fn: Callable[[float], None] = time.sleep,
                 clock_fn: Callable[[], float] = time.monotonic,
                 progress: Callable[[str], None] | None = None) -> None:
        self._inner = inner
        self._sleep = sleep_fn
        self._clock = clock_fn
        self._progress = progress
        self._last_attempt: dict[str, float] = {}
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def connect(self) -> None: self._inner.connect()
    def close(self) -> None: self._inner.close()

    def raw_tr(self, tr: str, values: dict[str, str]) -> dict[str, Any]:
        code = str(tr).strip().lower()
        used_quota_cooldown = False
        while True:
            for attempt in range(len(self._RETRY_DELAYS) + 1):
                self._pace(code)
                self._record_attempt(code)
                try:
                    return self._inner.raw_tr(tr, values)
                except Exception as exc:
                    if not self._is_retryable(exc):
                        raise
                    if attempt < len(self._RETRY_DELAYS):
                        delay = self._RETRY_DELAYS[attempt]
                        self._emit(f"[XING RETRY] {tr}: ETK_Request rejected; retry {attempt + 1}/{len(self._RETRY_DELAYS)} after {delay:.2f}s")
                        self._sleep(delay)
                        continue
                    if code == "t8429" and not used_quota_cooldown:
                        used_quota_cooldown = True
                        self._emit("[XING QUOTA] t8429 10분/200건 제한 가능성 감지; quota window reset까지 자동 대기")
                        self._countdown_sleep(self._EXTERNAL_QUOTA_COOLDOWN, tr)
                        self._attempts[code].clear()
                        self._last_attempt.pop(code, None)
                        break
                    raise
            else:
                raise RuntimeError("unreachable")
            if used_quota_cooldown:
                continue

    def _pace(self, code: str) -> None:
        self._wait_window(code)
        interval = self._TR_INTERVALS.get(code, self._DEFAULT_INTERVAL)
        now = self._clock(); prev = self._last_attempt.get(code)
        if prev is not None:
            remaining = interval - (now - prev)
            if remaining > 0: self._sleep(remaining); now = self._clock()
        self._last_attempt[code] = now

    def _wait_window(self, code: str) -> None:
        config = self._WINDOW_LIMITS.get(code)
        if not config: return
        limit, window = config
        q = self._attempts[code]; now = self._clock()
        while q and now - q[0] >= window: q.popleft()
        if len(q) < limit: return
        wait = max(0.0, window - (now - q[0]) + 1.0)
        self._emit(f"[XING QUOTA] {code}: {int(window/60)}분/{limit}건 한도 도달; {int(wait)//60:02d}:{int(wait)%60:02d} 대기")
        self._countdown_sleep(wait, code)
        now = self._clock()
        while q and now - q[0] >= window: q.popleft()

    def _record_attempt(self, code: str) -> None:
        q=self._attempts[code]; now=self._clock(); config=self._WINDOW_LIMITS.get(code)
        if config:
            _, window=config
            while q and now-q[0] >= window: q.popleft()
        q.append(now)

    def _countdown_sleep(self, seconds: float, label: str) -> None:
        remaining=max(0.0, seconds)
        while remaining > 0:
            step=min(30.0, remaining)
            self._sleep(step); remaining -= step
            if remaining > 0:
                self._emit(f"[XING QUOTA] {label}: 남은 대기 {int(remaining)//60:02d}:{int(remaining)%60:02d}")

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        text=f"{type(exc).__name__}: {exc}"
        return "ETK_Request" in text and ("실패" in text or "XingDllError" in text or "XingBridgeError" in text)

    def _emit(self, message: str) -> None:
        if self._progress is not None: self._progress(message)
