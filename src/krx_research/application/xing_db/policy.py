from __future__ import annotations

import datetime as dt


class DailyCloseWritePolicy:
    CUTOFF = dt.time(20, 10)

    @classmethod
    def resolve_end_date(cls, requested_end: dt.date, latest_market_date: dt.date | None, *, now: dt.datetime | None = None) -> dt.date:
        current = now or dt.datetime.now()
        if requested_end < current.date() or current.time() >= cls.CUTOFF:
            return requested_end
        safe_end = current.date() - dt.timedelta(days=1)
        if latest_market_date is not None and latest_market_date < current.date():
            safe_end = min(safe_end, latest_market_date)
        return min(requested_end, safe_end)

    @classmethod
    def assert_writable(cls, end_date: dt.date, *, now: dt.datetime | None = None) -> None:
        cls.resolve_end_date(end_date, None, now=now)


class SecurityMasterSyncPolicy:
    MINIMUM_ROWS = 1_000
    MAXIMUM_DROP_RATE = 0.1

    @classmethod
    def validate(cls, incoming: int, existing: int) -> None:
        minimum = max(cls.MINIMUM_ROWS, int(existing * (1 - cls.MAXIMUM_DROP_RATE)))
        if incoming < minimum:
            raise ValueError(
                f"t8436 종목 마스터 부분 수신: {incoming:,}건 "
                f"(필요 {minimum:,}건, 기존 {existing:,}건)"
            )
