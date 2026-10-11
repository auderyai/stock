"""Shared identifiers, dates, and errors for the public data collectors."""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
TICKER_PATTERN = re.compile(r"^\d{6}$")


class MarketDataError(RuntimeError):
    """A public data provider returned unusable data."""


def _retrieved_at() -> str:
    return dt.datetime.now(tz=KST).isoformat(timespec="seconds")


def normalize_ticker(value: object) -> str:
    ticker = str(value).strip().removesuffix(".0").zfill(6)
    if not TICKER_PATTERN.fullmatch(ticker):
        raise ValueError(f"Invalid KRX ticker: {value!r}")
    return ticker


def normalize_date(value: str | dt.date | dt.datetime) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return dt.date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"Unsupported date: {value!r}") from error
