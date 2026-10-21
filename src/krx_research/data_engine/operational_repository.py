from __future__ import annotations

from .postgresql import BaseDataRepository


class OperationalDataRepository:
    """Narrow repository facade used by maintenance command entry points."""

    def __init__(self, settings, application_name: str, *, read_only: bool = True) -> None:
        self._repository = BaseDataRepository(
            settings, application_name=application_name, read_only=read_only
        )

    def __enter__(self):
        self._repository.__enter__()
        return self

    def __exit__(self, *args):
        return self._repository.__exit__(*args)

    def initialize_schema(self):
        return self._repository.initialize_schema()

    def latest_ohlcv_date(self, ticker=None):
        return self._repository.latest_ohlcv_date(ticker)

    def latest_investor_date(self, ticker=None):
        return self._repository.latest_investor_date(ticker)

    def get_ohlcv(self, *args, **kwargs):
        return self._repository.get_ohlcv(*args, **kwargs)

    def get_investor_flow(self, *args, **kwargs):
        return self._repository.get_investor_flow(*args, **kwargs)

    def get_market_ohlcv(self, *args, **kwargs):
        return self._repository.get_market_ohlcv(*args, **kwargs)

    def get_security_master_frame(self):
        return self._repository.get_security_master_frame()

    def upsert_security_master(self, frame):
        return self._repository.upsert_security_master(frame)

    def upsert_ohlcv(self, frame):
        return self._repository.upsert_ohlcv(frame)

    def upsert_venue_ohlcv(self, *args, **kwargs):
        return self._repository.upsert_venue_ohlcv(*args, **kwargs)

    def missing_venue_dates(self, *args, **kwargs):
        return self._repository.missing_venue_dates(*args, **kwargs)
