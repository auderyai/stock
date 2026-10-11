"""Public KRX index-constituent lookup used by the workstation GUI."""

from __future__ import annotations

import datetime as dt
import html
import json
import math
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

from .common import MarketDataError, normalize_date, normalize_ticker


@dataclass(frozen=True)
class IndexDefinition:
    """Stable metadata for one index-backed workstation screen."""

    screen_type: str
    market: str
    display_name: str
    known_pykrx_code: str
    naver_code: str
    expected_count: int


INDEX_GAINER_DEFINITIONS = {
    "kospi200_daily_gainers": IndexDefinition(
        screen_type="kospi200_daily_gainers",
        market="KOSPI",
        display_name="KOSPI 200",
        known_pykrx_code="1028",
        naver_code="KPI200",
        expected_count=200,
    ),
    "kosdaq150_daily_gainers": IndexDefinition(
        screen_type="kosdaq150_daily_gainers",
        market="KOSDAQ",
        display_name="KOSDAQ 150",
        known_pykrx_code="2203",
        naver_code="KQ150",
        expected_count=150,
    ),
}
INDEX_GAINER_SCREEN_TYPES = frozenset(INDEX_GAINER_DEFINITIONS)


@dataclass(frozen=True)
class IndexMembership:
    """Validated constituents and their dated provider provenance."""

    screen_type: str
    index_code: str
    index_name: str
    as_of_date: dt.date
    tickers: tuple[str, ...]
    source: str = "pykrx:KRX_INDEX_PORTFOLIO"


KRX_INDEX_CONSTITUENTS_URL = (
    "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
)
NAVER_INDEX_ENTRY_URL = "https://finance.naver.com/sise/entryJongmok.naver"
KRX_HTTPS_SOURCE = "KRX:MDCSTAT00601_HTTPS"
NAVER_CURRENT_SOURCE = "NAVER:INDEX_ENTRY_CURRENT"
KST = ZoneInfo("Asia/Seoul")
MAX_RESPONSE_BYTES = 4_000_000
NAVER_RECENT_DATE_TOLERANCE_DAYS = 14
NAVER_PAGE_SIZE = 10
NAVER_MAX_WORKERS = 5


def _load_pykrx_stock() -> Any:
    try:
        from pykrx import stock
    except Exception as error:
        raise MarketDataError(f"pykrx import failed: {type(error).__name__}: {error}") from error
    return stock


def _normalize_constituents(values: object) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray, dict)) or not isinstance(
        values, Iterable
    ):
        raise MarketDataError("Index constituent rows are not a sequence")
    tickers: set[str] = set()
    for value in values:
        try:
            tickers.add(normalize_ticker(value))
        except ValueError:
            continue
    return tuple(sorted(tickers))


def _fetch_with_pykrx(
    stock_api: Any,
    code: str,
    as_of_date: dt.date,
) -> tuple[str, ...]:
    """Use pykrx without its broken empty-result holiday fallback."""

    values = stock_api.get_index_portfolio_deposit_file(
        code,
        date=as_of_date.strftime("%Y%m%d"),
        alternative=False,
    )
    return _normalize_constituents(values)


def _read_bounded_response(response: object) -> bytes:
    with response as opened:
        payload = opened.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise MarketDataError("Index constituent response is unexpectedly large")
    return payload


def _parse_krx_constituents(payload: bytes) -> tuple[str, ...]:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MarketDataError("Invalid KRX index constituent response") from error
    if not isinstance(document, dict):
        raise MarketDataError("Unexpected KRX index constituent document")
    rows = document.get("output")
    if rows is None:
        rows = document.get("OutBlock_1")
    if not isinstance(rows, list):
        raise MarketDataError("KRX index constituent rows are missing")
    values = [row.get("ISU_SRT_CD") for row in rows if isinstance(row, dict)]
    return _normalize_constituents(values)


def _fetch_krx_https(
    definition: IndexDefinition,
    as_of_date: dt.date,
    *,
    opener: Callable[..., object],
) -> tuple[str, ...]:
    code = definition.known_pykrx_code
    body = urllib.parse.urlencode(
        {
            "bld": "dbms/MDC/STAT/standard/MDCSTAT00601",
            "locale": "ko_KR",
            "indIdx": code[0],
            "indIdx2": code[1:],
            "trdDd": as_of_date.strftime("%Y%m%d"),
        }
    ).encode("ascii")
    request = urllib.request.Request(
        KRX_INDEX_CONSTITUENTS_URL,
        data=body,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://data.krx.co.kr",
            "Referer": (
                "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/"
                "index.cmd?menuId=MDC0201010101"
            ),
            "User-Agent": "Mozilla/5.0 KRX-Research-Workstation/25",
            "X-Requested-With": "XMLHttpRequest",
        },
        method="POST",
    )
    return _parse_krx_constituents(
        _read_bounded_response(opener(request, timeout=8.0))
    )


class _NaverConstituentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tickers: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "a":
            return
        href = next((value for key, value in attrs if key.casefold() == "href"), None)
        if not href:
            return
        parsed = urllib.parse.urlsplit(html.unescape(href))
        if not re.search(r"/item/(?:main\.(?:naver|nhn)|index)", parsed.path):
            return
        values = urllib.parse.parse_qs(parsed.query).get("code", [])
        if len(values) != 1 or not re.fullmatch(r"\d{6}", values[0]):
            return
        self.tickers.append(values[0])


def _parse_naver_constituents(payload: bytes) -> tuple[str, ...]:
    parser = _NaverConstituentParser()
    try:
        parser.feed(payload.decode("cp949", errors="replace"))
        parser.close()
    except Exception as error:
        raise MarketDataError("Invalid Naver index constituent response") from error
    return tuple(parser.tickers)


def _fetch_naver_page(
    definition: IndexDefinition,
    page: int,
    *,
    opener: Callable[..., object],
) -> tuple[str, ...]:
    query = urllib.parse.urlencode({"code": definition.naver_code, "page": page})
    request = urllib.request.Request(
        f"{NAVER_INDEX_ENTRY_URL}?{query}",
        headers={
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://finance.naver.com/",
            "User-Agent": "Mozilla/5.0 KRX-Research-Workstation/25",
        },
    )
    return _parse_naver_constituents(
        _read_bounded_response(opener(request, timeout=8.0))
    )


def _fetch_naver_current(
    definition: IndexDefinition,
    *,
    opener: Callable[..., object],
) -> tuple[str, ...]:
    page_count = math.ceil(definition.expected_count / NAVER_PAGE_SIZE)
    page_rows: dict[int, tuple[str, ...]] = {}
    page_errors: list[str] = []
    with ThreadPoolExecutor(max_workers=NAVER_MAX_WORKERS) as executor:
        futures = {
            executor.submit(_fetch_naver_page, definition, page, opener=opener): page
            for page in range(1, page_count + 1)
        }
        for future in as_completed(futures):
            page = futures[future]
            try:
                page_rows[page] = future.result()
            except Exception as error:  # noqa: BLE001
                page_errors.append(f"page {page}: {type(error).__name__}: {error}")

    for page in range(1, page_count + 1):
        if page_rows.get(page):
            continue
        try:
            page_rows[page] = _fetch_naver_page(
                definition,
                page,
                opener=opener,
            )
        except Exception as error:  # noqa: BLE001
            page_errors.append(
                f"retry page {page}: {type(error).__name__}: {error}"
            )

    values: list[str] = []
    for page in range(1, page_count + 1):
        values.extend(page_rows.get(page, ()))
    tickers = _normalize_constituents(values)
    minimum_count = max(30, math.ceil(definition.expected_count * 0.95))
    if len(tickers) < minimum_count:
        detail = f"; {' | '.join(page_errors[:3])}" if page_errors else ""
        raise MarketDataError(
            f"Naver returned only {len(tickers)}/{definition.expected_count} "
            f"{definition.display_name} constituents "
            f"(minimum accepted: {minimum_count}){detail}"
        )
    return tickers


def _is_recent_date(target_date: dt.date, today: dt.date) -> bool:
    age = (today - target_date).days
    return -1 <= age <= NAVER_RECENT_DATE_TOLERANCE_DAYS


def fetch_index_membership(
    screen_type: str,
    as_of_date: object,
    *,
    stock_api: Any | None = None,
    krx_opener: Callable[..., object] | None = None,
    naver_opener: Callable[..., object] | None = None,
    today: object | None = None,
) -> IndexMembership:
    """Fetch KOSPI 200 or KOSDAQ 150 constituents without KRX credentials.

    Provider order is pykrx, the same official KRX endpoint over HTTPS, then
    Naver's current index-entry pages for a recent trading date. pykrx's
    ``alternative=True`` path is deliberately avoided: when KRX returns no
    rows, pykrx 1.0.51 attempts an index-calendar lookup that can itself fail.
    """
    # LS_SCREEN_REPAIR_V2_MEMBERSHIP
    from .ls_index_membership import fetch_ls_membership
    return fetch_ls_membership(screen_type, as_of_date)

    try:
        definition = INDEX_GAINER_DEFINITIONS[screen_type]
    except KeyError as error:
        raise ValueError(f"Unsupported index-gainer screen: {screen_type!r}") from error
    target_date = normalize_date(as_of_date)
    code = definition.known_pykrx_code
    errors: list[str] = []
    current_date = (
        dt.datetime.now(tz=KST).date() if today is None else normalize_date(today)
    )
    if _is_recent_date(target_date, current_date):
        try:
            tickers = _fetch_naver_current(
                definition, opener=naver_opener or urllib.request.urlopen,
            )
        except Exception as error:
            raise MarketDataError(
                f"{definition.display_name} 최근 구성종목 조회 실패: "
                f"Naver {type(error).__name__}: {error}. "
                "KRX IP 제한 중에는 정확한 구성종목을 추측하지 않습니다."
            ) from error
        return IndexMembership(
            screen_type=screen_type,
            index_code=definition.naver_code,
            index_name=definition.display_name,
            as_of_date=current_date,
            tickers=tickers,
            source=NAVER_CURRENT_SOURCE,
        )
    try:
        api = stock_api if stock_api is not None else _load_pykrx_stock()
        tickers = _fetch_with_pykrx(api, code, target_date)
    except Exception as error:  # noqa: BLE001
        errors.append(f"pykrx={type(error).__name__}: {error}")
        tickers = ()
    if tickers:
        return IndexMembership(
            screen_type=screen_type,
            index_code=code,
            index_name=definition.display_name,
            as_of_date=target_date,
            tickers=tickers,
        )
    if not errors:
        errors.append("pykrx=empty")

    open_krx = krx_opener or urllib.request.urlopen
    krx_failed = False
    for offset in range(8):
        constituent_date = target_date - dt.timedelta(days=offset)
        try:
            tickers = _fetch_krx_https(
                definition,
                constituent_date,
                opener=open_krx,
            )
        except Exception as error:  # noqa: BLE001
            errors.append(f"KRX HTTPS={type(error).__name__}: {error}")
            krx_failed = True
            break
        if tickers:
            return IndexMembership(
                screen_type=screen_type,
                index_code=code,
                index_name=definition.display_name,
                as_of_date=constituent_date,
                tickers=tickers,
                source=KRX_HTTPS_SOURCE,
            )
    if not krx_failed:
        errors.append("KRX HTTPS=empty for target and prior 7 calendar days")

    errors.append("Naver=current-only fallback not used for non-recent target date")
    raise MarketDataError(
        f"{definition.display_name} constituents are unavailable for "
        f"{target_date.isoformat()}; {' | '.join(errors)}"
    )
