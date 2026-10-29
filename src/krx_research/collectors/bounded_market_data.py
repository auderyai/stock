from __future__ import annotations

from collections.abc import Callable
import multiprocessing as mp
from queue import Empty
from typing import Any

from pandas import DataFrame

from krx_research.collectors.market_data import MarketDataError


def _serve(
    requests: Any,
    responses: Any,
    fetcher: Callable[[str, object, object], DataFrame],
) -> None:
    while request := requests.get():
        ticker, start, end = request
        try:
            responses.put((True, fetcher(ticker, start, end)))
        except Exception as error:  # noqa: BLE001
            responses.put((False, f"{type(error).__name__}: {error}"))


class BoundedOhlcvFetcher:
    """Run an existing verified collector without allowing an infinite wait."""

    def __init__(
        self,
        fetcher: Callable[[str, object, object], DataFrame],
        *,
        timeout_seconds: float = 45.0,
    ) -> None:
        self._fetcher = fetcher
        self._timeout_seconds = timeout_seconds
        self._context = mp.get_context("spawn")
        self._requests: Any = None
        self._responses: Any = None
        self._process: Any = None

    def __enter__(self) -> BoundedOhlcvFetcher:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __call__(self, ticker: str, start: object, end: object) -> DataFrame:
        if self._process is None:
            self._start()
        self._requests.put((ticker, start, end))
        try:
            succeeded, result = self._responses.get(timeout=self._timeout_seconds)
        except Empty as error:
            self.close(force=True)
            raise MarketDataError(
                f"OHLCV provider timeout after {self._timeout_seconds:g}s: {ticker}"
            ) from error
        if not succeeded:
            raise MarketDataError(str(result))
        return result

    def _start(self) -> None:
        self._requests = self._context.Queue(1)
        self._responses = self._context.Queue(1)
        self._process = self._context.Process(
            target=_serve,
            args=(self._requests, self._responses, self._fetcher),
            daemon=True,
        )
        self._process.start()

    def close(self, *, force: bool = False) -> None:
        if self._process is None:
            return
        if not force:
            self._requests.put(None)
            self._process.join(1.0)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(1.0)
        self._requests.close()
        self._responses.close()
        self._process = self._requests = self._responses = None
