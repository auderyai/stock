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
