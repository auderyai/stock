"""Login-free public fallbacks for theme market and trading-value facts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Iterable

import pandas as pd

from krx_research.collectors.xing_t8451 import XingT8451Client
from krx_research.collectors.naver_history import (
    DATE_RANGE_SOURCE,
    DATE_RANGE_URL,
    fetch_naver_date_range_ohlcv,
)
from krx_research.collectors.market_data import fetch_security_master
from krx_research.data_engine.providers import PykrxBaseProvider

KRX_SOURCE_URL = "https://data.krx.co.kr/"
MARKETS = ("KOSPI", "KOSDAQ")


def fetch_public_security_names(
    names: Iterable[str],
    *,
    fetcher: Callable[[], pd.DataFrame] | None = None,
) -> tuple[dict[str, dict[str, str | None]], list[str]]:
    """Leave names not present in the local master unresolved without network access."""

    requested = {str(name).strip() for name in names if str(name).strip()}
    if not requested:
        return {}, []
    return {}, [f"종목명 '{name}'은 로컬 종목 DB에 없어 코드 미확인" for name in sorted(requested)]


@dataclass(frozen=True)
class PublicThemeFact:
    ticker: str
    trade_date: date
    market: str | None
    trading_value: Decimal | None
    source: str
    source_url: str
    is_estimate: bool = False


def _decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    result = Decimal(str(value))
    return result if result > 0 else None


def _krx_facts(
    report_date: date,
    requested: set[str],
    provider: Any,
) -> tuple[dict[str, PublicThemeFact], list[str]]:
    facts: dict[str, PublicThemeFact] = {}
    errors: list[str] = []
    for market in MARKETS:
        try:
            frame = provider.fetch_ohlcv(report_date, market)
        except Exception as error:  # provider boundary
            errors.append(f"{market} KRX: {type(error).__name__}: {error}")
            continue
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            errors.append(f"{market} KRX: 빈 자료")
            continue
        for row in frame.to_dict("records"):
            ticker = str(row.get("stock_code") or "").strip().zfill(6)
            if ticker not in requested:
                continue
            amount = _decimal(row.get("amount"))
            source = str(row.get("source") or "KRX:MDCSTAT01501_HTTPS")
            facts[ticker] = PublicThemeFact(
                ticker=ticker,
                trade_date=report_date,
                market=market,
                trading_value=amount,
                source=source,
                source_url=KRX_SOURCE_URL,
                is_estimate=False,
            )
    return facts, errors


def _naver_fact(
    ticker: str,
    report_date: date,
    fetcher: Callable[..., pd.DataFrame],
) -> PublicThemeFact | None:
    frame = fetcher(ticker, report_date, report_date)
    if frame.empty:
        return None
    exact = frame.loc[pd.DatetimeIndex(frame.index).date == report_date]
    if exact.empty:
        return None
    row = exact.iloc[-1]
    close = _decimal(row.get("close"))
    volume = _decimal(row.get("volume"))
    if close is None or volume is None:
        return None
    return PublicThemeFact(
        ticker=ticker,
        trade_date=report_date,
        market=None,
        trading_value=close * volume,
        source=f"{DATE_RANGE_SOURCE}:close_x_volume",
        source_url=DATE_RANGE_URL,
        is_estimate=True,
    )


def fetch_public_theme_facts(
    report_date: date,
    tickers: Iterable[str],
    *,
    provider: Any | None = None,
    naver_fetcher: Callable[..., pd.DataFrame] = fetch_naver_date_range_ohlcv,
    max_workers: int = 6,
    include_naver: bool = True,
    naver_tickers: Iterable[str] | None = None,
) -> tuple[dict[str, PublicThemeFact], list[str]]:
    """Fetch exact-date LS t8451 turnover for facts missing from the local DB."""

    requested = {str(value).strip().zfill(6) for value in tickers if str(value).strip()}
    if not requested:
        return {}, []
    facts: dict[str, PublicThemeFact] = {}
    errors: list[str] = []
    own_client = provider is None
    try:
        if own_client:
            provider = XingT8451Client.from_environment(Path(__file__).resolve().parents[3])
        for ticker in sorted(requested):
            try:
                frame = provider.fetch(ticker, report_date, report_date, 'COMBINED')
                if frame is None or frame.empty:
                    errors.append(f"{ticker} LS: 해당 날짜 자료 없음")
                    continue
                exact = frame.loc[pd.to_datetime(frame['trade_date']).dt.date.eq(report_date)]
                if exact.empty:
                    errors.append(f"{ticker} LS: 해당 날짜 자료 없음")
                    continue
                amount = _decimal(exact.iloc[-1].get('amount'))
                if amount is None:
                    errors.append(f"{ticker} LS: 거래대금 없음")
                    continue
                facts[ticker] = PublicThemeFact(ticker, report_date, None, amount,
                                               'LS_XING:t8451:COMBINED',
                                               'LS xingAPI COM', False)
            except Exception as error:
                errors.append(f"{ticker} LS: {type(error).__name__}: {error}")
    except Exception as error:
        errors.append(f"LS 인증: {type(error).__name__}: {error}")
    finally:
        if own_client and provider is not None:
            provider.close()
    return facts, errors


__all__ = ["PublicThemeFact", "fetch_public_theme_facts", "fetch_public_security_names"]
