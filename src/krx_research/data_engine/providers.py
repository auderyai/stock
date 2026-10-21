from __future__ import annotations

import io
import json
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from krx_research.analytics.investor import PROVIDER_TO_CODE

MARKETS = ("KOSPI", "KOSDAQ", "KONEX")
MARKET_TO_KRX_ID = {"KOSPI": "STK", "KOSDAQ": "KSQ", "KONEX": "KNX"}
PROVIDER_INVESTORS = (
    "금융투자",
    "보험",
    "투신",
    "사모",
    "은행",
    "기타금융",
    "연기금",
    "기타법인",
    "개인",
    "외국인",
    "기타외국인",
)
INVESTOR_TO_KRX_CODE = {
    "금융투자": "1000",
    "보험": "2000",
    "투신": "3000",
    "사모": "3100",
    "은행": "4000",
    "기타금융": "5000",
    "연기금": "6000",
    "기타법인": "7100",
    "개인": "8000",
    "외국인": "9000",
    "기타외국인": "9001",
}

KRX_DATA_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_OHLCV_BLD = "dbms/MDC/STAT/standard/MDCSTAT01501"
KRX_INVESTOR_BLD = "dbms/MDC/STAT/standard/MDCSTAT02401"
MAX_RESPONSE_BYTES = 16_000_000


class BaseDataSourceError(RuntimeError):
    """A recoverable market-data source failure, not a database failure."""


def _compact_error(error: BaseException, *, limit: int = 180) -> str:
    message = " ".join(str(error).split()) or type(error).__name__
    if len(message) > limit:
        message = f"{message[: limit - 1]}…"
    return f"{type(error).__name__}: {message}"


def _pykrx_stock():
    """Import pykrx without its optional-login warning.

    The v1.2 line prints a KRX_ID/KRX_PW warning at import time even though the
    public routes used here do not require a login. Pykrx remains a secondary
    route when the direct official response is temporarily malformed.
    """

    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            from pykrx import stock
    except ImportError as exc:
        raise BaseDataSourceError(
            "pykrx가 설치되지 않았습니다. requirements-data-engine-v30.txt를 설치하십시오."
        ) from exc
    return stock


def _find_column(frame: pd.DataFrame, *names: str) -> str | None:
    normalized = {str(column).replace(" ", ""): str(column) for column in frame.columns}
    for name in names:
        found = normalized.get(name.replace(" ", ""))
        if found is not None:
            return found
    return None


def _read_response(response: object) -> bytes:
    opened = response
    enter = getattr(response, "__enter__", None)
    if callable(enter):
        opened = enter()
    try:
        reader = getattr(opened, "read", None)
        if not callable(reader):
            raise TypeError("KRX 응답 객체에 read()가 없습니다.")
        payload = reader(MAX_RESPONSE_BYTES + 1)
    finally:
        exit_method = getattr(response, "__exit__", None)
        if callable(exit_method):
            exit_method(None, None, None)
        else:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("KRX 응답 크기가 허용 범위를 초과했습니다.")
    return payload


def _fetch_krx_json(
    parameters: dict[str, str],
    *,
    opener: Callable[..., object],
) -> dict[str, Any]:
    body = urllib.parse.urlencode(parameters).encode("ascii")
    request = urllib.request.Request(
        KRX_DATA_URL,
        data=body,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://data.krx.co.kr",
            "Referer": (
                "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/"
                "index.cmd?menuId=MDC0201020101"
            ),
            "User-Agent": "Mozilla/5.0 KRX-Research-Workstation/31",
            "X-Requested-With": "XMLHttpRequest",
        },
        method="POST",
    )
    payload = _read_response(opener(request, timeout=15.0))
    try:
        document = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("KRX가 JSON이 아닌 응답을 반환했습니다.") from exc
    if not isinstance(document, dict):
        raise TypeError("KRX 응답 형식이 객체가 아닙니다.")
    error_code = str(document.get("_error_code") or "").strip()
    if error_code and error_code not in {"CD001", "0"}:
        message = " ".join(str(document.get("_error_message") or "").split())
        raise ValueError(f"KRX 오류 {error_code}: {message or '상세 메시지 없음'}")
    return document


def _response_rows(document: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        if key not in document:
            continue
        rows = document[key]
        if not isinstance(rows, list):
            raise TypeError(f"KRX 응답의 {key} 항목이 목록이 아닙니다.")
        return [row for row in rows if isinstance(row, dict)]
    raise ValueError(f"KRX 응답에 자료 행({', '.join(keys)})이 없습니다.")


def _official_ohlcv(
    target_date: date,
    market: str,
    *,
    opener: Callable[..., object],
) -> pd.DataFrame:
    document = _fetch_krx_json(
        {
            "bld": KRX_OHLCV_BLD,
            "locale": "ko_KR",
            "mktId": MARKET_TO_KRX_ID[market],
            "trdDd": target_date.strftime("%Y%m%d"),
            "share": "1",
            "money": "1",
            "csvxls_isNo": "false",
        },
        opener=opener,
    )
    return pd.DataFrame(_response_rows(document, "OutBlock_1", "output"))


def _official_investor(
    target_date: date,
    market: str,
    investor_name: str,
    *,
    opener: Callable[..., object],
) -> pd.DataFrame:
    date_text = target_date.strftime("%Y%m%d")
    document = _fetch_krx_json(
        {
            "bld": KRX_INVESTOR_BLD,
            "locale": "ko_KR",
            "strtDd": date_text,
            "endDd": date_text,
            "mktId": MARKET_TO_KRX_ID[market],
            "invstTpCd": INVESTOR_TO_KRX_CODE[investor_name],
            "share": "1",
            "money": "1",
            "csvxls_isNo": "false",
        },
        opener=opener,
    )
    return pd.DataFrame(_response_rows(document, "output", "OutBlock_1"))


def _numeric(series: pd.Series, *, integer: bool = False) -> pd.Series:
    result = pd.to_numeric(
        series.astype("string").str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )
    if integer:
        return result.fillna(0).round().astype("int64")
    return result


def _normalize_ohlcv(
    frame: pd.DataFrame,
    target_date: date,
    *,
    source: str,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.reset_index()
    ticker_column = _find_column(result, "ISU_SRT_CD", "티커", "종목코드", "ticker")
    rename = {
        ticker_column: "stock_code",
        _find_column(result, "TDD_OPNPRC", "시가", "open"): "open_price",
        _find_column(result, "TDD_HGPRC", "고가", "high"): "high_price",
        _find_column(result, "TDD_LWPRC", "저가", "low"): "low_price",
        _find_column(result, "TDD_CLSPRC", "종가", "close"): "close_price",
        _find_column(result, "ACC_TRDVOL", "거래량", "volume"): "volume",
        _find_column(result, "ACC_TRDVAL", "거래대금", "amount", "value"): "amount",
        _find_column(result, "FLUC_RT", "등락률", "change_rate"): "change_rate",
    }
    required = {
        "stock_code",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "amount",
    }
    found = {value for key, value in rename.items() if key is not None}
    if missing := sorted(required.difference(found)):
        raise ValueError(f"가격 응답 필수 열이 변경되었습니다: {missing}")
    result = result.rename(columns={key: value for key, value in rename.items() if key is not None})
    result["stock_code"] = (
        result["stock_code"].astype("string").str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    )
    for column in ("open_price", "high_price", "low_price", "close_price"):
        result[column] = _numeric(result[column])
    result = result.loc[result["stock_code"].notna() & result["close_price"].gt(0)].copy()
    if result.empty:
        return pd.DataFrame()
    for column in ("open_price", "high_price", "low_price"):
        result[column] = result[column].where(result[column].gt(0), result["close_price"])
    result["volume"] = _numeric(result["volume"], integer=True)
    result["amount"] = _numeric(result["amount"], integer=True)
    if "change_rate" in result:
        result["change_rate"] = _numeric(result["change_rate"])
    else:
        result["change_rate"] = pd.NA
    result["trade_date"] = pd.Timestamp(target_date)
    result["source"] = source
    # The new cross-section is the current adjustment base and must remain
    # visible to the existing adjusted_only read path.
    result["adjusted"] = True
    return result[
        [
            "stock_code",
            "trade_date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "amount",
            "change_rate",
            "source",
            "adjusted",
        ]
    ].drop_duplicates("stock_code", keep="first").reset_index(drop=True)


def _normalize_investor(
    frame: pd.DataFrame,
    target_date: date,
    investor_name: str,
    *,
    source: str,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.reset_index()
    ticker_column = _find_column(result, "ISU_SRT_CD", "티커", "종목코드", "ticker")
    rename: dict[str | None, str] = {
        ticker_column: "stock_code",
        _find_column(result, "BID_TRDVOL", "매수거래량", "매수량"): "buy_volume",
        _find_column(result, "ASK_TRDVOL", "매도거래량", "매도량"): "sell_volume",
        _find_column(result, "BID_TRDVAL", "매수거래대금", "매수대금"): "buy_value",
        _find_column(result, "ASK_TRDVAL", "매도거래대금", "매도대금"): "sell_value",
    }
    required = {"stock_code", "buy_volume", "sell_volume", "buy_value", "sell_value"}
    found = {value for key, value in rename.items() if key is not None}
    if missing := sorted(required.difference(found)):
        raise ValueError(f"수급 응답 필수 열이 변경되었습니다: {missing}")
    result = result.rename(columns={key: value for key, value in rename.items() if key is not None})
    result["stock_code"] = (
        result["stock_code"].astype("string").str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    )
    result = result.loc[result["stock_code"].notna()].copy()
    values = ("buy_volume", "sell_volume", "buy_value", "sell_value")
    for column in values:
        result[column] = _numeric(result[column], integer=True)
    result["trade_date"] = pd.Timestamp(target_date)
    result["investor_type"] = PROVIDER_TO_CODE[investor_name]
    result["source"] = source
    nonzero = result[list(values)].ne(0).any(axis=1)
    return result.loc[
        nonzero,
        ["stock_code", "trade_date", "investor_type", *values, "source"],
    ].drop_duplicates("stock_code", keep="first").reset_index(drop=True)


class PykrxBaseProvider:
    """Market-wide base facts with official login-free HTTPS first.

    The class name is retained for compatibility with the v30 entry points.
    Current data uses the official KRX JSON routes directly; pykrx is a quiet
    secondary path when the public response is temporarily malformed.
    """

    def __init__(
        self,
        delay_seconds: float = 0.35,
        *,
        opener: Callable[..., object] | None = None,
        fallback_universe: pd.DataFrame | None = None,
        current_quote_fetcher: Callable[..., object] | None = None,
    ) -> None:
        self.delay_seconds = max(0.0, delay_seconds)
        self.opener = opener or urllib.request.urlopen
        self.fallback_universe = (
            None if fallback_universe is None else fallback_universe.copy(deep=True)
        )
        self.current_quote_fetcher = current_quote_fetcher
        self._current_price_cache: tuple[date, str, pd.DataFrame] | None = None

    def _delay(self) -> None:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)

    def _fetch_current_price_fallback(
        self,
        target_date: date,
        market: str,
    ) -> pd.DataFrame:
        if self.fallback_universe is None or self.fallback_universe.empty:
            return pd.DataFrame()
        today_kst = datetime.now(ZoneInfo("Asia/Seoul")).date()
        # Naver's public polling snapshot carries the latest completed trading
        # date.  It is therefore also the correct fallback on weekends and the
        # morning after a failed final KRX collection, not only on calendar
        # "today".  The exact response date is validated below before use.
        age_days = (today_kst - target_date).days
        if age_days < 0 or age_days > 7 or market == "KONEX":
            return pd.DataFrame()
        cached = self._current_price_cache
        if cached is None or cached[0] != target_date:
            fetcher = self.current_quote_fetcher
            is_default_fetcher = fetcher is None
            if is_default_fetcher:
                from krx_research.collectors.realtime_quotes import (
                    fetch_realtime_krx_quotes,
                )

                fetcher = fetch_realtime_krx_quotes
            universe = self.fallback_universe.rename(
                columns={"stock_code": "ticker", "stock_name": "name"}
            ).copy()
            if is_default_fetcher:
                snapshot = fetcher(
                    target_date,
                    universe=universe,
                    max_prior_days=0,
                    naver_min_market_coverage=0.85,
                    naver_tolerate_batch_errors=True,
                )
            else:
                snapshot = fetcher(
                    target_date,
                    universe=universe,
                    max_prior_days=0,
                )
            snapshot_date = getattr(snapshot, "as_of_date", None)
            if snapshot_date != target_date:
                raise ValueError(
                    "현재 시세 기준일 불일치: "
                    f"요청 {target_date.isoformat()}, 응답 {snapshot_date}"
                )
            rows = getattr(snapshot, "rows", None)
            if not isinstance(rows, pd.DataFrame) or rows.empty:
                raise ValueError("현재 시세 보조 공급원이 빈 자료를 반환했습니다.")
            self._current_price_cache = (
                target_date,
                str(getattr(snapshot, "source", "CURRENT_QUOTE_FALLBACK")),
                rows.copy(deep=True),
            )
            cached = self._current_price_cache
        assert cached is not None
        source = cached[1]
        rows = cached[2]
        selected = rows.loc[rows["market"].astype(str).eq(market)].copy()
        if selected.empty:
            return pd.DataFrame()
        result = selected.rename(
            columns={
                "ticker": "stock_code",
                "open": "open_price",
                "high": "high_price",
                "low": "low_price",
                "close": "close_price",
                "trading_value": "amount",
                "daily_return_pct": "change_rate",
            }
        )
        result["trade_date"] = pd.Timestamp(target_date)
        result["source"] = source
        result["adjusted"] = True
        return result[
            [
                "stock_code",
                "trade_date",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "volume",
                "amount",
                "change_rate",
                "source",
                "adjusted",
            ]
        ].reset_index(drop=True)

    def fetch_ohlcv(self, target_date: date, market: str) -> pd.DataFrame:
        if market not in MARKETS:
            raise ValueError(f"지원하지 않는 시장: {market}")
        errors: list[str] = []
        empty_response: pd.DataFrame | None = None
        try:
            frame = _official_ohlcv(target_date, market, opener=self.opener)
            self._delay()
            normalized = _normalize_ohlcv(
                frame, target_date, source="KRX:MDCSTAT01501_HTTPS"
            )
            if not normalized.empty:
                return normalized
            empty_response = normalized
            errors.append("공식 KRX=빈 자료")
        except Exception as error:  # noqa: BLE001 - provider boundary
            errors.append(f"공식 KRX={_compact_error(error)}")

        try:
            fallback = self._fetch_current_price_fallback(target_date, market)
            if not fallback.empty:
                return fallback
        except Exception as error:  # noqa: BLE001 - provider boundary
            errors.append(f"현재 시세 보조 공급원={_compact_error(error)}")

        try:
            stock = _pykrx_stock()
            date_text = target_date.strftime("%Y%m%d")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                method = getattr(stock, "get_market_ohlcv_by_ticker", None)
                if callable(method):
                    frame = method(date_text, market=market)
                else:
                    frame = stock.get_market_ohlcv(date_text, market=market)
            self._delay()
            normalized = _normalize_ohlcv(frame, target_date, source="pykrx")
            if not normalized.empty:
                return normalized
            empty_response = normalized
            errors.append("pykrx=빈 자료")
        except Exception as error:  # noqa: BLE001 - provider boundary
            errors.append(f"pykrx={_compact_error(error)}")
        if empty_response is not None:
            return empty_response
        raise BaseDataSourceError(
            f"{market} {target_date.isoformat()} 가격 수집 실패. " + " / ".join(errors)
        )

    def fetch_investor_flow(self, target_date: date, market: str) -> pd.DataFrame:
        if market not in MARKETS:
            raise ValueError(f"지원하지 않는 시장: {market}")
        output: list[pd.DataFrame] = []
        stock: Any | None = None
        for investor_name in PROVIDER_INVESTORS:
            errors: list[str] = []
            try:
                frame = _official_investor(
                    target_date,
                    market,
                    investor_name,
                    opener=self.opener,
                )
                self._delay()
                normalized = _normalize_investor(
                    frame,
                    target_date,
                    investor_name,
                    source="KRX:MDCSTAT02401_HTTPS",
                )
            except Exception as error:  # noqa: BLE001 - provider boundary
                errors.append(f"공식 KRX={_compact_error(error)}")
                try:
                    stock = stock or _pykrx_stock()
                    date_text = target_date.strftime("%Y%m%d")
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        method = getattr(
                            stock,
                            "get_market_net_purchases_of_equities_by_ticker",
                            None,
                        )
                        if not callable(method):
                            method = stock.get_market_net_purchases_of_equities
                        frame = method(date_text, date_text, market, investor_name)
                    self._delay()
                    normalized = _normalize_investor(
                        frame,
                        target_date,
                        investor_name,
                        source="pykrx",
                    )
                except Exception as fallback_error:
                    errors.append(f"pykrx={_compact_error(fallback_error)}")
                    raise BaseDataSourceError(
                        f"{market} {target_date.isoformat()} {investor_name} 수급 수집 실패. "
                        + " / ".join(errors)
                    ) from fallback_error
            if not normalized.empty:
                output.append(normalized)

        if output:
            return pd.concat(output, ignore_index=True)

        # All-empty investor output is legitimate only when the market closed.
        # When prices exist, keep the date retryable rather than recording a
        # false zero-flow completion.
        try:
            prices = _official_ohlcv(target_date, market, opener=self.opener)
            normalized_prices = _normalize_ohlcv(
                prices,
                target_date,
                source="KRX:MDCSTAT01501_HTTPS",
            )
        except Exception as error:
            raise BaseDataSourceError(
                f"{market} {target_date.isoformat()} 수급 자료가 비어 있고 거래일 확인도 실패했습니다: "
                f"{_compact_error(error)}"
            ) from error
        if normalized_prices.empty:
            return pd.DataFrame()
        raise BaseDataSourceError(
            f"{market} {target_date.isoformat()} 가격은 있으나 확정 수급 자료가 아직 제공되지 않았습니다. "
            "20:10(KST) 이후 다시 실행하십시오."
        )
