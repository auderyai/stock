"""Login-free current KOSPI/KOSDAQ quote snapshots from public routes."""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from pandas import DataFrame

from .common import MarketDataError, normalize_date, normalize_ticker

KST = ZoneInfo("Asia/Seoul")
NAVER_CURRENT_QUOTE_URL = (
    "https://polling.finance.naver.com/api/realtime/domestic/stock/{codes}"
)
KRX_MARKET_QUOTE_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
NAVER_CURRENT_SOURCE = "NAVER:POLLING_DOMESTIC_STOCK"
NAVER_KRX_SOURCE = f"{NAVER_CURRENT_SOURCE}:KRX"
NAVER_NXT_SOURCE = f"{NAVER_CURRENT_SOURCE}:NXT"
NAVER_COMBINED_SOURCE = f"{NAVER_CURRENT_SOURCE}:KRX+NXT"
PYKRX_CURRENT_SOURCE = "pykrx:KRX_CURRENT"
KRX_HTTPS_CURRENT_SOURCE = "KRX:MDCSTAT01501_HTTPS"
QUOTE_VENUE_KRX = "KRX"
QUOTE_VENUE_NXT = "NXT"
QUOTE_VENUE_COMBINED = "COMBINED"
QUOTE_VENUES = frozenset({QUOTE_VENUE_KRX, QUOTE_VENUE_NXT, QUOTE_VENUE_COMBINED})
MAX_RESPONSE_BYTES = 8_000_000
NAVER_BATCH_SIZE = 100
NAVER_MIN_MARKET_COVERAGE = 0.95
MARKET_IDS = {"KOSPI": "STK", "KOSDAQ": "KSQ"}
REQUIRED_QUOTE_COLUMNS = {
    "ticker",
    "market",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trading_value",
    "daily_return_pct",
}


@dataclass(frozen=True)
class RealtimeQuoteSnapshot:
    """Validated cross-market quotes and their retrieval provenance."""

    as_of_date: dt.date
    retrieved_at: dt.datetime
    source: str
    rows: DataFrame


def _load_pykrx_stock() -> Any:
    try:
        from pykrx import stock
    except Exception as error:
        raise MarketDataError(
            f"pykrx import failed: {type(error).__name__}: {error}"
        ) from error
    return stock


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype("string").str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )


def _normalize_quote_frame(
    frame: DataFrame,
    *,
    market: str,
    trade_date: dt.date | None,
) -> DataFrame:
    if frame.empty:
        raise MarketDataError(f"{market} current quote response returned no rows")
    if missing := REQUIRED_QUOTE_COLUMNS.difference(frame.columns):
        raise MarketDataError(
            f"{market} current quote response missing columns: {sorted(missing)}"
        )

    work = frame.copy()
    normalized: list[str | None] = []
    for value in work["ticker"]:
        try:
            normalized.append(normalize_ticker(value))
        except ValueError:
            normalized.append(None)
    work["ticker"] = pd.Series(normalized, index=work.index, dtype="string")
    work = work.loc[work["ticker"].notna()].copy()

    for column in (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trading_value",
        "daily_return_pct",
    ):
        work[column] = _numeric(work[column])
    work = work.loc[work["close"].gt(0)].copy()
    if work.empty:
        raise MarketDataError(f"{market} current quote response has no positive prices")

    # KRX reports zero OHLC for suspended securities.  Retain their latest close
    # without allowing a zero high/low to create a false breakout.
    for column in ("open", "high", "low"):
        work[column] = work[column].where(work[column].gt(0), work["close"])
    work["volume"] = work["volume"].fillna(0).clip(lower=0).round().astype("int64")
    work["trading_value"] = work["trading_value"].fillna(0).clip(lower=0)
    work["market"] = market
    if trade_date is not None:
        work["trade_date"] = pd.Timestamp(trade_date)
    else:
        work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
        work = work.loc[work["trade_date"].notna()].copy()
        if work.empty:
            raise MarketDataError(f"{market} current quote response has no trade dates")
        work["trade_date"] = work["trade_date"].dt.normalize()
    if "name" not in work:
        work["name"] = pd.NA
    work["name"] = work["name"].astype("string").str.strip().replace("", pd.NA)
    work = work.drop_duplicates("ticker", keep="first")
    return work[
        [
            "ticker",
            "name",
            "market",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "trading_value",
            "daily_return_pct",
        ]
    ].reset_index(drop=True)


def _fetch_pykrx_market(
    stock_api: Any,
    market: str,
    trade_date: dt.date,
) -> DataFrame:
    frame = stock_api.get_market_ohlcv_by_ticker(
        trade_date.strftime("%Y%m%d"),
        market=market,
        alternative=False,
    )
    if not isinstance(frame, DataFrame):
        raise MarketDataError(f"pykrx returned a non-DataFrame {market} response")
    work = frame.reset_index()
    ticker_column = "티커" if "티커" in work else work.columns[0]
    work = work.rename(
        columns={
            ticker_column: "ticker",
            "시가": "open",
            "고가": "high",
            "저가": "low",
            "종가": "close",
            "거래량": "volume",
            "거래대금": "trading_value",
            "등락률": "daily_return_pct",
        }
    )
    work["market"] = market
    work["trade_date"] = pd.Timestamp(trade_date)
    return _normalize_quote_frame(work, market=market, trade_date=trade_date)


def _read_bounded_response(response: object) -> bytes:
    with response as opened:
        payload = opened.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise MarketDataError("Current quote response is unexpectedly large")
    return payload


def _normalize_universe(universe: DataFrame) -> DataFrame:
    if not isinstance(universe, DataFrame) or universe.empty:
        raise MarketDataError("DB 종목 목록이 없어 네이버 현재 시세를 조회할 수 없습니다.")
    if missing := {"ticker", "market"}.difference(universe.columns):
        raise MarketDataError(f"DB 종목 목록에 필요한 열이 없습니다: {sorted(missing)}")

    work = universe.copy()
    normalized: list[str | None] = []
    for value in work["ticker"]:
        try:
            normalized.append(normalize_ticker(value))
        except ValueError:
            normalized.append(None)
    work["ticker"] = pd.Series(normalized, index=work.index, dtype="string")
    work["market"] = work["market"].astype("string").str.upper().str.strip()
    work = work.loc[
        work["ticker"].notna() & work["market"].isin(MARKET_IDS)
    ].copy()
    if work.empty:
        raise MarketDataError("DB 종목 목록에 KOSPI/KOSDAQ 종목이 없습니다.")
    if "name" not in work:
        work["name"] = pd.NA
    if "trade_date" not in work:
        work["trade_date"] = pd.NaT
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    return work.drop_duplicates("ticker", keep="first").reset_index(drop=True)


def _document_rows(document: object) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        raise MarketDataError("Unexpected Naver current quote document")

    candidates: list[object] = [document.get("datas")]
    result = document.get("result")
    if isinstance(result, dict):
        candidates.append(result.get("datas"))
        areas = result.get("areas")
        if isinstance(areas, list):
            service_areas = [
                area
                for area in areas
                if isinstance(area, dict) and area.get("name") == "SERVICE_ITEM"
            ]
            other_areas = [area for area in areas if area not in service_areas]
            for area in [*service_areas, *other_areas]:
                if isinstance(area, dict):
                    candidates.append(area.get("datas"))
    for candidate in candidates:
        if isinstance(candidate, list):
            rows = [row for row in candidate if isinstance(row, dict)]
            if rows:
                return rows
    raise MarketDataError("Naver current quote rows are missing")


def _nested_value(row: dict[str, Any], *keys: str) -> Any:
    wanted = set(keys)
    pending: list[object] = [row]
    while pending:
        value = pending.pop(0)
        if not isinstance(value, dict):
            continue
        for key, child in value.items():
            if key in wanted and child not in (None, ""):
                return child
            if isinstance(child, dict):
                pending.append(child)
    return None


def _preferred_nested_value(row: dict[str, Any], *keys: str) -> Any:
    """Return the first named field in caller priority order."""

    for key in keys:
        value = _nested_value(row, key)
        if value not in (None, ""):
            return value
    return None


def _direct_value(row: dict[str, Any], *keys: str) -> Any:
    """Read only this venue's object, never a nested alternate-market quote."""

    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _nxt_quote(row: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("nxtOverMarketPriceInfo", "overMarketPriceInfo"):
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return None


_KOREAN_NUMBER_UNITS = {
    "조": 1_000_000_000_000.0,
    "억": 100_000_000.0,
    "백만": 1_000_000.0,
    "만": 10_000.0,
    "천": 1_000.0,
}


def _naver_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    text = text.replace("원", "").replace("주", "").strip()
    if not text or text in {"-", "--", "N/A"}:
        return None
    multiplier = 1.0
    for suffix, unit in _KOREAN_NUMBER_UNITS.items():
        if text.endswith(suffix):
            multiplier = unit
            text = text[: -len(suffix)].strip()
            break
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    return float(match.group()) * multiplier


def _naver_trade_date(row: dict[str, Any]) -> dt.date | None:
    value = _nested_value(
        row,
        "localTradedAt",
        "tradeDate",
        "businessDay",
        "date",
    )
    if value in (None, ""):
        return None
    text = str(value).strip()
    match = re.search(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})", text)
    if match is None:
        return None
    try:
        return dt.date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _direct_trade_date(row: dict[str, Any]) -> dt.date | None:
    value = _direct_value(row, "localTradedAt", "tradeDate", "businessDay", "date")
    if value in (None, ""):
        return None
    match = re.search(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})", str(value).strip())
    if match is None:
        return None
    try:
        return dt.date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _parse_naver_market_quotes(
    payload: bytes,
    *,
    universe: DataFrame,
    fallback_date: dt.date,
    venue: str = QUOTE_VENUE_KRX,
) -> DataFrame:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MarketDataError("Invalid Naver current quote response") from error

    metadata = universe.set_index("ticker")[["name", "market"]].to_dict("index")
    if venue not in QUOTE_VENUES:
        raise ValueError(f"Unsupported quote venue: {venue!r}")
    krx_rows: list[dict[str, Any]] = []
    nxt_rows: list[dict[str, Any]] = []
    for row in _document_rows(document):
        raw_ticker = _direct_value(
            row,
            "itemCode",
            "stockCode",
            "symbolCode",
            "code",
            "cd",
        )
        try:
            ticker = normalize_ticker(raw_ticker)
        except (TypeError, ValueError):
            continue
        details = metadata.get(ticker)
        if details is None:
            continue
        krx_rows.append(
            {
                "ticker": ticker,
                "name": _direct_value(row, "stockName", "itemName", "nm")
                or details["name"],
                "market": details["market"],
                "trade_date": _direct_trade_date(row),
                "open": _naver_number(
                    _direct_value(
                        row, "openPriceRaw", "openPrice", "openingPrice", "open", "ov"
                    )
                ),
                "high": _naver_number(
                    _direct_value(
                        row, "highPriceRaw", "highPrice", "highestPrice", "high", "hv"
                    )
                ),
                "low": _naver_number(
                    _direct_value(
                        row, "lowPriceRaw", "lowPrice", "lowestPrice", "low", "lv"
                    )
                ),
                "close": _naver_number(
                    _direct_value(
                        row, "closePriceRaw", "closePrice", "currentPrice", "nowVal", "nv"
                    )
                ),
                "volume": _naver_number(
                    _direct_value(
                        row,
                        "accumulatedTradingVolumeRaw",
                        "accumulatedTradingVolume",
                        "accumulatedVolume",
                        "volume",
                        "aq",
                    )
                ),
                "trading_value": _naver_number(
                    _direct_value(
                        row,
                        "accumulatedTradingValueRaw",
                        "accumulatedTradingValue",
                        "accumulatedTradingAmount",
                        "tradingValue",
                        "aa",
                    )
                ),
                "daily_return_pct": _naver_number(
                    _direct_value(
                        row,
                        "fluctuationsRatio",
                        "fluctuationRate",
                        "changeRate",
                        "cr",
                    )
                ),
            }
        )
        nxt = _nxt_quote(row)
        if nxt is not None:
            nxt_rows.append(
                {
                    "ticker": ticker,
                    "name": details["name"],
                    "market": details["market"],
                    "trade_date": _direct_trade_date(nxt),
                    "open": _naver_number(
                        _direct_value(nxt, "openPriceRaw", "openPrice", "open")
                    ),
                    "high": _naver_number(
                        _direct_value(nxt, "highPriceRaw", "highPrice", "high")
                    ),
                    "low": _naver_number(
                        _direct_value(nxt, "lowPriceRaw", "lowPrice", "low")
                    ),
                    "close": _naver_number(
                        _direct_value(
                            nxt,
                            "overPriceRaw",
                            "overPrice",
                            "closePriceRaw",
                            "closePrice",
                            "currentPrice",
                        )
                    ),
                    "volume": _naver_number(
                        _direct_value(
                            nxt,
                            "accumulatedTradingVolumeRaw",
                            "accumulatedTradingVolume",
                            "accumulatedVolume",
                            "volume",
                        )
                    ),
                    "trading_value": _naver_number(
                        _direct_value(
                            nxt,
                            "accumulatedTradingValueRaw",
                            "accumulatedTradingValue",
                            "accumulatedTradingAmount",
                            "tradingValue",
                        )
                    ),
                    "daily_return_pct": _naver_number(
                        _direct_value(
                            nxt,
                            "fluctuationsRatio",
                            "fluctuationRate",
                            "changeRate",
                        )
                    ),
                }
            )

    krx_frame = DataFrame(krx_rows)
    nxt_frame = DataFrame(nxt_rows)
    if venue == QUOTE_VENUE_KRX:
        frame = krx_frame
    elif venue == QUOTE_VENUE_NXT:
        frame = nxt_frame
    else:
        frame = _combine_naver_venues(krx_frame, nxt_frame)
    if frame.empty:
        raise MarketDataError("Naver current quote response has no requested tickers")

    available_dates = pd.Series(
        [value for value in frame["trade_date"] if value is not None],
        dtype="object",
    )
    common_date = (
        available_dates.mode().iloc[0] if not available_dates.empty else fallback_date
    )
    frame["trade_date"] = frame["trade_date"].fillna(common_date)
    normalized_frames = [
        _normalize_quote_frame(
            market_rows,
            market=market,
            trade_date=None,
        )
        for market, market_rows in frame.groupby("market", sort=False)
    ]
    return pd.concat(normalized_frames, ignore_index=True)


def _combine_naver_venues(krx: DataFrame, nxt: DataFrame) -> DataFrame:
    """Combine venue OHLCV without confusing NXT fields with KRX fields."""

    if krx.empty or nxt.empty:
        return krx.copy()
    nxt_indexed = nxt.drop_duplicates("ticker", keep="first").set_index("ticker")

    def choose(primary: object, fallback: object) -> object:
        return primary if primary is not None and not pd.isna(primary) else fallback

    combined: list[dict[str, Any]] = []
    for krx_row in krx.to_dict("records"):
        ticker = str(krx_row["ticker"])
        if ticker not in nxt_indexed.index:
            combined.append(krx_row)
            continue
        nxt_row = nxt_indexed.loc[ticker].to_dict()
        row = dict(krx_row)
        for column, reducer in (("high", max), ("low", min)):
            values = [
                value
                for value in (
                    _naver_number(krx_row.get(column)),
                    _naver_number(nxt_row.get(column)),
                )
                if value is not None
            ]
            row[column] = reducer(values) if values else None
        row["open"] = choose(nxt_row.get("open"), krx_row.get("open"))
        row["close"] = choose(nxt_row.get("close"), krx_row.get("close"))
        row["daily_return_pct"] = choose(
            nxt_row.get("daily_return_pct"),
            krx_row.get("daily_return_pct"),
        )
        for column in ("volume", "trading_value"):
            row[column] = sum(
                value or 0
                for value in (
                    _naver_number(krx_row.get(column)),
                    _naver_number(nxt_row.get(column)),
                )
            )
        row["trade_date"] = choose(
            nxt_row.get("trade_date"),
            krx_row.get("trade_date"),
        )
        combined.append(row)
    return DataFrame(combined)


def _fetch_naver_current_quotes(
    universe: DataFrame,
    *,
    opener: Callable[..., object],
    fallback_date: dt.date,
    batch_size: int = NAVER_BATCH_SIZE,
    retry_attempts: int = 2,
    minimum_market_coverage: float = NAVER_MIN_MARKET_COVERAGE,
    tolerate_batch_errors: bool = False,
    venue: str = QUOTE_VENUE_KRX,
) -> DataFrame:
    if batch_size < 1 or batch_size > 200:
        raise ValueError("Naver batch_size must be between 1 and 200")
    if retry_attempts < 1 or retry_attempts > 3:
        raise ValueError("Naver retry_attempts must be between 1 and 3")
    if not 0 < minimum_market_coverage <= 1:
        raise ValueError("minimum_market_coverage must be in (0, 1]")
    requested = _normalize_universe(universe)
    frames: list[DataFrame] = []
    tickers = requested["ticker"].astype(str).tolist()
    for start in range(0, len(tickers), batch_size):
        batch = tickers[start : start + batch_size]
        url = NAVER_CURRENT_QUOTE_URL.format(codes=",".join(batch))
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://finance.naver.com/",
                "User-Agent": "Mozilla/5.0 KRX-Research-Workstation/27",
            },
            method="GET",
        )
        last_error: Exception | None = None
        for _attempt in range(retry_attempts):
            try:
                payload = _read_bounded_response(opener(request, timeout=10.0))
                frames.append(
                    _parse_naver_market_quotes(
                        payload,
                        universe=requested.loc[requested["ticker"].isin(batch)],
                        fallback_date=fallback_date,
                        venue=venue,
                    )
                )
            except Exception as error:  # noqa: BLE001
                last_error = error
            else:
                break
        else:
            assert last_error is not None
            if not tolerate_batch_errors:
                raise MarketDataError(
                    f"Naver batch {start // batch_size + 1} failed: "
                    f"{type(last_error).__name__}: {last_error}"
                ) from last_error

    if not frames:
        raise MarketDataError("All Naver current quote batches failed")

    result = pd.concat(frames, ignore_index=True).drop_duplicates(
        "ticker", keep="first"
    )
    for market in MARKET_IDS:
        expected = int(requested["market"].eq(market).sum())
        actual = int(result["market"].eq(market).sum())
        minimum = (
            1
            if venue == QUOTE_VENUE_NXT and expected
            else math.ceil(expected * minimum_market_coverage)
        )
        if expected and actual < minimum:
            raise MarketDataError(
                f"Naver {market} coverage is {actual}/{expected}; "
                f"at least {minimum} rows are required"
            )
    return _combine_markets(
        [result.loc[result["market"].eq(market)].copy() for market in MARKET_IDS]
    )


def _parse_krx_market_quotes(
    payload: bytes,
    *,
    market: str,
    trade_date: dt.date,
) -> DataFrame:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MarketDataError("Invalid KRX current quote response") from error
    if not isinstance(document, dict):
        raise MarketDataError("Unexpected KRX current quote document")
    rows = document.get("OutBlock_1")
    if rows is None:
        rows = document.get("output")
    if not isinstance(rows, list):
        raise MarketDataError("KRX current quote rows are missing")
    frame = DataFrame(row for row in rows if isinstance(row, dict)).rename(
        columns={
            "ISU_SRT_CD": "ticker",
            "ISU_ABBRV": "name",
            "TDD_OPNPRC": "open",
            "TDD_HGPRC": "high",
            "TDD_LWPRC": "low",
            "TDD_CLSPRC": "close",
            "ACC_TRDVOL": "volume",
            "ACC_TRDVAL": "trading_value",
            "FLUC_RT": "daily_return_pct",
        }
    )
    frame["market"] = market
    frame["trade_date"] = pd.Timestamp(trade_date)
    return _normalize_quote_frame(frame, market=market, trade_date=trade_date)


def _fetch_krx_https_market(
    market: str,
    trade_date: dt.date,
    *,
    opener: Callable[..., object],
) -> DataFrame:
    body = urllib.parse.urlencode(
        {
            "bld": "dbms/MDC/STAT/standard/MDCSTAT01501",
            "locale": "ko_KR",
            "mktId": MARKET_IDS[market],
            "trdDd": trade_date.strftime("%Y%m%d"),
            "share": "1",
            "money": "1",
            "csvxls_isNo": "false",
        }
    ).encode("ascii")
    request = urllib.request.Request(
        KRX_MARKET_QUOTE_URL,
        data=body,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://data.krx.co.kr",
            "Referer": (
                "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/"
                "index.cmd?menuId=MDC0201020101"
            ),
            "User-Agent": "Mozilla/5.0 KRX-Research-Workstation/27",
            "X-Requested-With": "XMLHttpRequest",
        },
        method="POST",
    )
    payload = _read_bounded_response(opener(request, timeout=10.0))
    return _parse_krx_market_quotes(
        payload,
        market=market,
        trade_date=trade_date,
    )


def _combine_markets(frames: list[DataFrame]) -> DataFrame:
    result = pd.concat(frames, ignore_index=True)
    if result["ticker"].duplicated().any():
        duplicates = result.loc[result["ticker"].duplicated(), "ticker"].tolist()
        raise MarketDataError(f"Current quote response has duplicate tickers: {duplicates[:10]}")
    markets = set(result["market"])
    if markets != set(MARKET_IDS):
        raise MarketDataError(f"Current quote response has incomplete markets: {sorted(markets)}")
    result["_market_order"] = result["market"].map({"KOSPI": 0, "KOSDAQ": 1})
    return (
        result.sort_values(["_market_order", "ticker"], kind="mergesort")
        .drop(columns="_market_order")
        .reset_index(drop=True)
    )


def fetch_realtime_krx_quotes(
    as_of_date: object | None = None,
    *,
    universe: DataFrame | None = None,
    stock_api: Any | None = None,
    naver_opener: Callable[..., object] | None = None,
    krx_opener: Callable[..., object] | None = None,
    max_prior_days: int = 7,
    naver_recent_days: int = 7,
    naver_min_market_coverage: float = NAVER_MIN_MARKET_COVERAGE,
    naver_tolerate_batch_errors: bool = False,
    venue: str = QUOTE_VENUE_KRX,
) -> RealtimeQuoteSnapshot:
    """Return the latest public cross-section on or before ``as_of_date``.

    With a DB universe, Naver's public batch quote route is attempted first.
    Public pykrx and official KRX ``MDCSTAT01501`` HTTPS are retained as
    fallbacks.  No login or credentials are used.
    """

    venue = str(venue).strip().upper()
    if venue not in QUOTE_VENUES:
        raise ValueError(f"Unsupported quote venue: {venue!r}")
    if max_prior_days < 0 or max_prior_days > 14:
        raise ValueError("max_prior_days must be between 0 and 14")
    if naver_recent_days < 0 or naver_recent_days > 14:
        raise ValueError("naver_recent_days must be between 0 and 14")
    target = (
        dt.datetime.now(tz=KST).date()
        if as_of_date is None
        else normalize_date(as_of_date)
    )
    provider_errors: dict[str, str] = {}
    today = dt.datetime.now(tz=KST).date()

    if universe is not None and today - dt.timedelta(days=naver_recent_days) <= target <= today:
        try:
            normalized_universe = _normalize_universe(universe)
            universe_dates = normalized_universe["trade_date"].dropna()
            fallback_date = (
                universe_dates.max().date() if not universe_dates.empty else target
            )
            rows = _fetch_naver_current_quotes(
                normalized_universe,
                opener=naver_opener or urllib.request.urlopen,
                fallback_date=fallback_date,
                minimum_market_coverage=naver_min_market_coverage,
                tolerate_batch_errors=naver_tolerate_batch_errors,
                venue=venue,
            )
            current_date = pd.to_datetime(rows["trade_date"]).max().date()
            if current_date > target or (target - current_date).days > max_prior_days:
                raise MarketDataError(
                    f"Naver returned out-of-range trade date {current_date.isoformat()}"
                )
            rows = rows.loc[
                pd.to_datetime(rows["trade_date"]).dt.date.eq(current_date)
            ].copy()
            rows = _combine_markets(
                [rows.loc[rows["market"].eq(market)].copy() for market in MARKET_IDS]
            )
        except Exception as error:  # noqa: BLE001
            provider_errors["Naver"] = _compact_error(error)
        else:
            return RealtimeQuoteSnapshot(
                as_of_date=current_date,
                retrieved_at=dt.datetime.now(tz=KST),
                source={
                    QUOTE_VENUE_KRX: NAVER_KRX_SOURCE,
                    QUOTE_VENUE_NXT: NAVER_NXT_SOURCE,
                    QUOTE_VENUE_COMBINED: NAVER_COMBINED_SOURCE,
                }[venue],
                rows=rows,
            )

    if venue != QUOTE_VENUE_KRX:
        detail = " / ".join(
            f"{provider}={message}" for provider, message in provider_errors.items()
        )
        raise MarketDataError(
            f"{venue} 실시간 시세를 네이버 응답에서 확인할 수 없습니다. "
            f"공급자 응답: {detail}"
        )

    try:
        api = stock_api if stock_api is not None else _load_pykrx_stock()
    except Exception as error:  # noqa: BLE001
        provider_errors["pykrx"] = _compact_error(error)
        api = None
    opener = krx_opener or urllib.request.urlopen

    for offset in range(max_prior_days + 1):
        quote_date = target - dt.timedelta(days=offset)
        if quote_date.weekday() >= 5:
            continue
        if api is not None:
            try:
                rows = _combine_markets(
                    [
                        _fetch_pykrx_market(api, market, quote_date)
                        for market in MARKET_IDS
                    ]
                )
            except Exception as error:  # noqa: BLE001
                provider_errors["pykrx"] = _compact_error(error)
            else:
                return RealtimeQuoteSnapshot(
                    as_of_date=quote_date,
                    retrieved_at=dt.datetime.now(tz=KST),
                    source=PYKRX_CURRENT_SOURCE,
                    rows=rows,
                )

        try:
            rows = _combine_markets(
                [
                    _fetch_krx_https_market(
                        market,
                        quote_date,
                        opener=opener,
                    )
                    for market in MARKET_IDS
                ]
            )
        except Exception as error:  # noqa: BLE001
            provider_errors["KRX"] = _compact_error(error)
        else:
            return RealtimeQuoteSnapshot(
                as_of_date=quote_date,
                retrieved_at=dt.datetime.now(tz=KST),
                source=KRX_HTTPS_CURRENT_SOURCE,
                rows=rows,
            )

    detail = " / ".join(
        f"{provider}={message}" for provider, message in provider_errors.items()
    )
    raise MarketDataError(
        "실시간 시세 조회 실패 (Naver → pykrx → KRX). "
        "네트워크 또는 공급자 상태를 확인하거나 Data Base를 선택하세요. "
        f"기준일 {target.isoformat()}. 공급자 응답: {detail}"
    )


def _compact_error(error: Exception, *, limit: int = 140) -> str:
    message = " ".join(str(error).split()) or type(error).__name__
    if len(message) > limit:
        message = f"{message[: limit - 1]}…"
    return f"{type(error).__name__}: {message}"
