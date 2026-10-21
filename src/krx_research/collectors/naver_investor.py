"""Bounded public Naver investor-trend collector for one selected security."""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

import pandas as pd
from pandas import DataFrame

NAVER_INVESTOR_TREND_URL = "https://m.stock.naver.com/front-api/stock/domestic/trend"
NAVER_INVESTOR_TREND_COUNT = 800
NAVER_INVESTOR_PAGE_SIZE = 100
NAVER_INVESTOR_MAX_RESPONSE_BYTES = 2_000_000
NAVER_INVESTOR_TIMEOUT_SECONDS = 20.0
NAVER_INVESTOR_RETRIES = 2


def _read_bounded_response(response: object, *, limit: int) -> bytes:
    opened = response
    enter = getattr(response, "__enter__", None)
    if callable(enter):
        opened = enter()
    try:
        reader = getattr(opened, "read", None)
        if not callable(reader):
            raise TypeError("Naver 응답 객체에 read()가 없습니다.")
        payload = reader(limit + 1)
    finally:
        exit_method = getattr(response, "__exit__", None)
        if callable(exit_method):
            exit_method(None, None, None)
        else:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    if len(payload) > limit:
        raise ValueError("Naver 수급 응답 크기가 허용 범위를 초과했습니다.")
    return payload


def _naver_trend_page(
    document: object,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    if isinstance(document, list):
        return [row for row in document if isinstance(row, dict)], None, False
    if not isinstance(document, dict):
        raise TypeError("Naver 수급 응답 형식이 객체 또는 목록이 아닙니다.")

    result = document.get("result")
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)], None, False
    if isinstance(result, dict):
        rows = result.get("items")
        if isinstance(rows, list):
            cursor = str(result.get("cursor") or "").strip() or None
            return (
                [row for row in rows if isinstance(row, dict)],
                cursor,
                bool(result.get("hasNext")),
            )
    for key in ("list", "investorList", "investors", "trendList", "data"):
        rows = document.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)], None, False
    raise ValueError("Naver 수급 응답에 자료 목록이 없습니다.")


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _integer_value(value: object) -> int:
    if value is None:
        return 0
    text = str(value).strip().replace(",", "").replace("+", "")
    if not text or text in {"-", "--"}:
        return 0
    try:
        return int(round(float(text)))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Naver 수급 숫자 형식 오류: {value!r}") from error


def _trend_date(value: object) -> pd.Timestamp:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 8:
        return pd.NaT
    return pd.to_datetime(digits[:8], format="%Y%m%d", errors="coerce")


def fetch_naver_investor_trend(
    ticker: object,
    *,
    count: int = NAVER_INVESTOR_TREND_COUNT,
    opener: Callable[..., object] | None = None,
) -> DataFrame:
    """Fetch aggregate net flows for one selected ticker, never market-wide.

    Naver exposes signed net-buy quantities for institutions, foreigners, and
    individuals. The chart's value series is an explicit estimate calculated
    as signed quantity multiplied by that day's close; nothing is persisted.
    """

    match = re.fullmatch(r"\d{1,6}", str(ticker).strip())
    if match is None:
        raise ValueError(f"종목코드 형식 오류: {ticker!r}")
    code = match.group(0).zfill(6)
    bounded_count = min(max(int(count), 1), NAVER_INVESTOR_TREND_COUNT)
    open_url = opener or urllib.request.urlopen
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    requested_urls: list[str] = []
    source_warning = ""
    while len(rows) < bounded_count:
        parameters = {
            "code": code,
            "exchangeType": "KRX",
            "size": min(NAVER_INVESTOR_PAGE_SIZE, bounded_count - len(rows)),
        }
        if cursor:
            parameters["cursor"] = cursor
        url = f"{NAVER_INVESTOR_TREND_URL}?{urllib.parse.urlencode(parameters)}"
        requested_urls.append(url)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": (
                    f"https://m.stock.naver.com/domestic/stock/{code}/tradingTrend"
                    "?stockEndTradingTrendExchange=KRX"
                ),
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/128 Safari/537.36"
                ),
                "x-for-krx-extension": "true",
            },
        )
        payload: bytes | None = None
        last_error: BaseException | None = None
        for _attempt in range(NAVER_INVESTOR_RETRIES):
            try:
                payload = _read_bounded_response(
                    open_url(request, timeout=NAVER_INVESTOR_TIMEOUT_SECONDS),
                    limit=NAVER_INVESTOR_MAX_RESPONSE_BYTES,
                )
                break
            except (TimeoutError, urllib.error.URLError) as error:
                last_error = error
        if payload is None:
            if not rows and last_error is not None:
                raise last_error
            source_warning = (
                "다음 수급 페이지 조회 실패로 확보된 구간까지만 표시합니다: "
                f"{type(last_error).__name__}"
            )
            break
        try:
            document = json.loads(payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Naver가 JSON이 아닌 수급 응답을 반환했습니다.") from error
        page_rows, next_cursor, has_next = _naver_trend_page(document)
        if not page_rows:
            break
        rows.extend(page_rows[: bounded_count - len(rows)])
        if not has_next or not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    mappings = (
        (
            "INSTITUTION_TOTAL",
            (
                "organizationNetVolume",
                "organPureBuyQuant",
                "institutionPureBuyQuant",
            ),
        ),
        (
            "FOREIGN_TOTAL",
            ("foreignNetVolume", "foreignerPureBuyQuant", "foreignPureBuyQuant"),
        ),
        (
            "INDIVIDUAL",
            ("individualNetVolume", "individualPureBuyQuant", "personalPureBuyQuant"),
        ),
    )
    normalized: list[dict[str, object]] = []
    for row in rows:
        market_row = row.get("krx")
        values = {**row, **market_row} if isinstance(market_row, dict) else row
        trade_date = _trend_date(
            _first_value(
                values,
                "localTradedAt",
                "bizdate",
                "stcTrdDd",
                "bizday",
                "date",
            )
        )
        if pd.isna(trade_date):
            continue
        close_price = _integer_value(
            _first_value(
                values,
                "closingPrice",
                "closePrice",
                "close",
                "localTradedPrice",
            )
        )
        if close_price <= 0:
            continue
        for investor_type, keys in mappings:
            net_volume = _integer_value(_first_value(values, *keys))
            net_value = net_volume * close_price
            normalized.append(
                {
                    "stock_code": code,
                    "trade_date": trade_date,
                    "investor_type": investor_type,
                    "buy_volume": max(net_volume, 0),
                    "sell_volume": max(-net_volume, 0),
                    "buy_value": max(net_value, 0),
                    "sell_value": max(-net_value, 0),
                    "source": "NAVER:FRONT_TREND_PUBLIC",
                    "source_url": NAVER_INVESTOR_TREND_URL,
                    "source_date": trade_date,
                }
            )
    if not normalized:
        raise ValueError(f"Naver 공개 수급 응답에 {code}의 유효한 행이 없습니다.")
    frame = DataFrame(normalized).drop_duplicates(
        ["stock_code", "trade_date", "investor_type"], keep="last"
    )
    frame = frame.sort_values(["trade_date", "investor_type"], ignore_index=True)
    frame.attrs = {
        "source": "NAVER:FRONT_TREND_PUBLIC",
        "source_url": NAVER_INVESTOR_TREND_URL,
        "source_label": "Naver 공개 수급 · 순매수수량×종가 추정",
        "estimated_value": True,
        "source_rows": int(frame["trade_date"].nunique()),
        "source_requests": len(requested_urls),
        "source_warning": source_warning,
        "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return frame
