"""Google News lookup for dated, source-labelled stock-rise reasons."""

from __future__ import annotations

import datetime as dt
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

from krx_research.collectors import normalize_ticker
from krx_research.collectors.common import normalize_date

KST = ZoneInfo("Asia/Seoul")
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
GOOGLE_NEWS_SEARCH_URL = "https://www.google.com/search"
MAX_RSS_BYTES = 2_000_000
DEFAULT_NEWS_LIMIT = 5


class RiseReasonLookupError(RuntimeError):
    """Raised when Google News cannot be queried or parsed safely."""


@dataclass(frozen=True)
class GoogleNewsItem:
    title: str
    source: str
    published_at: dt.datetime | None
    link: str


@dataclass(frozen=True)
class RiseReasonReport:
    ticker: str
    company_name: str
    as_of_date: dt.date
    searched_at: dt.datetime
    query: str
    feed_url: str
    search_url: str
    items: tuple[GoogleNewsItem, ...]


def build_google_news_query(
    company_name: object,
    ticker: object,
    as_of_date: object,
) -> str:
    """Build a narrow Korean-news query around the selected trading date."""

    name = str(company_name).strip()
    if not name:
        raise ValueError("company_name must not be empty")
    code = normalize_ticker(ticker)
    target_date = normalize_date(as_of_date)
    date_from = target_date - dt.timedelta(days=1)
    date_until = target_date + dt.timedelta(days=2)
    return (
        f'"{name}" ({code} OR 상승 OR 강세 OR 급등 OR 상한가 OR 신고가) '
        f"after:{date_from.isoformat()} before:{date_until.isoformat()}"
    )


def build_google_news_urls(query: str) -> tuple[str, str]:
    """Return the RSS endpoint and a browser-friendly Google News search."""

    cleaned = str(query).strip()
    if not cleaned:
        raise ValueError("query must not be empty")
    feed_url = (
        GOOGLE_NEWS_RSS_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "q": cleaned,
                "hl": "ko",
                "gl": "KR",
                "ceid": "KR:ko",
            }
        )
    )
    search_url = GOOGLE_NEWS_SEARCH_URL + "?" + urllib.parse.urlencode({"tbm": "nws", "q": cleaned})
    return feed_url, search_url


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _safe_http_link(value: str | None) -> str:
    link = _clean_text(value)
    parsed = urllib.parse.urlparse(link)
    return link if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _published_at(value: str | None) -> dt.datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(KST)


def parse_google_news_rss(
    payload: bytes, *, limit: int = DEFAULT_NEWS_LIMIT
) -> tuple[GoogleNewsItem, ...]:
    """Parse a bounded Google News RSS response into display-safe values."""

    if limit < 1:
        raise ValueError("limit must be positive")
    if len(payload) > MAX_RSS_BYTES:
        raise RiseReasonLookupError("Google 뉴스 응답이 허용 크기를 초과했습니다.")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise RiseReasonLookupError(f"Google 뉴스 RSS 형식 오류: {error}") from error

    result: list[GoogleNewsItem] = []
    seen: set[str] = set()
    for element in root.findall("./channel/item"):
        title = _clean_text(element.findtext("title"))
        link = _safe_http_link(element.findtext("link"))
        source = _clean_text(element.findtext("source"))
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)].strip()
        elif not source and " - " in title:
            possible_title, possible_source = title.rsplit(" - ", 1)
            if len(possible_source) <= 80:
                title = possible_title.strip()
                source = possible_source.strip()
        identity = re.sub(r"\W+", "", title).casefold()
        if not title or not link or not identity or identity in seen:
            continue
        seen.add(identity)
        result.append(
            GoogleNewsItem(
                title=title,
                source=source or "매체 미표시",
                published_at=_published_at(element.findtext("pubDate")),
                link=link,
            )
        )
        if len(result) >= limit:
            break
    return tuple(result)


def _default_open(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_google_rise_reason(
    company_name: object,
    ticker: object,
    as_of_date: object,
    *,
    opener: Callable[[urllib.request.Request, float], Any] = _default_open,
    timeout: float = 8.0,
    limit: int = DEFAULT_NEWS_LIMIT,
) -> RiseReasonReport:
    """Fetch dated Google News headlines that may explain a daily rise."""

    if timeout <= 0:
        raise ValueError("timeout must be positive")
    name = str(company_name).strip()
    code = normalize_ticker(ticker)
    target_date = normalize_date(as_of_date)
    query = build_google_news_query(name, code, target_date)
    feed_url, search_url = build_google_news_urls(query)
    request = urllib.request.Request(
        feed_url,
        headers={
            "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8",
            "User-Agent": "Mozilla/5.0 (compatible; KRX-Research-Workstation/1.0)",
        },
    )
    try:
        with opener(request, timeout) as response:
            payload = response.read(MAX_RSS_BYTES + 1)
    except Exception as error:
        raise RiseReasonLookupError(
            f"Google 뉴스 조회 실패: {type(error).__name__}: {error}"
        ) from error
    items = parse_google_news_rss(payload, limit=limit)
    return RiseReasonReport(
        ticker=code,
        company_name=name,
        as_of_date=target_date,
        searched_at=dt.datetime.now(tz=KST),
        query=query,
        feed_url=feed_url,
        search_url=search_url,
        items=items,
    )


def format_rise_reason_report(report: RiseReasonReport) -> str:
    """Format a concise, auditable explanation for the chart footer."""

    prefix = (
        f"{report.as_of_date.isoformat()} 상승 사유 후보 · Google 뉴스 기사 제목 기반"
        "(인과관계 확정 아님)"
    )
    if not report.items:
        return ""

    lines = [prefix, f"주요 후보: {report.items[0].title}"]
    for number, item in enumerate(report.items[:3], 1):
        published = (
            item.published_at.strftime("%m-%d %H:%M")
            if item.published_at is not None
            else "시각 미표시"
        )
        lines.append(f"{number}. [{published} · {item.source}] {item.title}")
    return "\n".join(lines)
