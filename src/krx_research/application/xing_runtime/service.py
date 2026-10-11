from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from typing import Any, Protocol

from .models import QualificationReport, TrQualificationResult


class RawTrPort(Protocol):
    def connect(self) -> None: ...
    def raw_tr(self, tr: str, values: dict[str, str]) -> dict[str, Any]: ...


ProgressCallback = Callable[[int, int, str, TrQualificationResult | None], None]


class XingRuntimeQualificationService:
    """Qualifies the six required LS DLL TRs without leaking DLL logic into the UI.

    The service first asks t8424/t8436 for live identifiers.  The derived sector and
    stock codes are then reused by t8429/t1516/t8451/t1702, avoiding environment-
    specific hard-coded test instruments where possible.
    """

    REQUIRED_TRS = ("t8424", "t8436", "t8429", "t8451", "t1516", "t1702")
    _PREFERRED_STOCKS = ("005930", "000660", "035420", "051910")
    _PREFERRED_SECTOR_NAMES = ("코스피200", "kospi200")

    def __init__(self, bridge: RawTrPort, *, today: dt.date | None = None) -> None:
        self._bridge = bridge
        self._today = today or dt.date.today()

    def qualify(self, progress: ProgressCallback | None = None) -> QualificationReport:
        total = len(self.REQUIRED_TRS) + 1
        self._emit(progress, 1, total, "DLL worker/login", None)
        self._bridge.connect()

        results: list[TrQualificationResult] = []

        t8424 = self._run(
            "t8424", {"gubun1": "0"}, required_fields=("upcode", "hname")
        )
        results.append(t8424)
        self._emit(progress, 2, total, "t8424", t8424)
        if not t8424.passed:
            return QualificationReport(True, tuple(results))

        sector_rows = self._last_rows
        sector_code = self._pick_sector_code(sector_rows)

        t8436 = self._run(
            "t8436", {"gubun": "0"}, required_fields=("shcode", "hname")
        )
        results.append(t8436)
        self._emit(progress, 3, total, "t8436", t8436)
        if not t8436.passed:
            return QualificationReport(True, tuple(results), sector_code=sector_code)

        stock_rows = self._last_rows
        stock_code = self._pick_stock_code(stock_rows)
        start = self._today - dt.timedelta(days=45)
        date_values = {"sdate": start.strftime("%Y%m%d"), "edate": self._today.strftime("%Y%m%d")}

        cases = (
            (
                "t8429",
                {
                    "shcode": sector_code, "gubun": "2", "qrycnt": "200",
                    **date_values, "cts_date": "", "comp_yn": "N",
                },
                ("date", "close"),
            ),
            (
                "t8451",
                {
                    "shcode": stock_code, "gubun": "2", "qrycnt": "200",
                    **date_values, "cts_date": "", "comp_yn": "N", "sujung": "N",
                    "exchgubun": "K",
                },
                ("date", "close"),
            ),
            (
                "t1516",
                {"upcode": sector_code, "gubun": "1", "shcode": ""},
                ("shcode",),
            ),
            (
                "t1702",
                {
                    "fromdt": start.strftime("%Y%m%d"), "shcode": stock_code,
                    "todt": self._today.strftime("%Y%m%d"), "volvalgb": "0",
                    "msmdgb": "1", "gubun": "0", "exchgubun": "K",
                },
                ("date",),
            ),
        )

        for offset, (tr_code, values, fields) in enumerate(cases, start=4):
            result = self._run(tr_code, values, required_fields=fields)
            results.append(result)
            self._emit(progress, offset, total, tr_code, result)

        return QualificationReport(
            login_passed=True,
            results=tuple(results),
            stock_code=stock_code,
            sector_code=sector_code,
        )

    _last_rows: list[dict[str, Any]]

    def _run(
        self,
        tr_code: str,
        values: dict[str, str],
        *,
        required_fields: tuple[str, ...],
    ) -> TrQualificationResult:
        try:
            response = self._bridge.raw_tr(tr_code, values)
            rows = response.get("rows")
            if not isinstance(rows, list):
                self._last_rows = []
                return TrQualificationResult(tr_code, False, 0, "rows가 list가 아닙니다.")
            clean_rows = [row for row in rows if isinstance(row, dict)]
            self._last_rows = clean_rows
            if not clean_rows:
                return TrQualificationResult(tr_code, False, 0, "응답 행이 없습니다.")
            sample = clean_rows[0]
            missing = [name for name in required_fields if name not in sample]
            if missing:
                return TrQualificationResult(
                    tr_code, False, len(clean_rows), f"필수 필드 누락: {', '.join(missing)}", sample
                )
            return TrQualificationResult(tr_code, True, len(clean_rows), "PASS", sample)
        except Exception as exc:
            self._last_rows = []
            return TrQualificationResult(tr_code, False, 0, f"{type(exc).__name__}: {exc}")

    @classmethod
    def _pick_stock_code(cls, rows: list[dict[str, Any]]) -> str:
        available = {
            str(row.get("shcode") or "").strip()
            for row in rows
            if re.fullmatch(r"\d{6}", str(row.get("shcode") or "").strip())
        }
        for code in cls._PREFERRED_STOCKS:
            if code in available:
                return code
        if available:
            return sorted(available)[0]
        raise ValueError("t8436에서 6자리 숫자 종목코드를 찾지 못했습니다.")

    @classmethod
    def _pick_sector_code(cls, rows: list[dict[str, Any]]) -> str:
        def norm(value: object) -> str:
            return re.sub(r"[\s_-]+", "", str(value or "")).lower()

        preferred = {norm(name) for name in cls._PREFERRED_SECTOR_NAMES}
        for row in rows:
            code = str(row.get("upcode") or "").strip()
            if re.fullmatch(r"\d{3}", code) and norm(row.get("hname")) in preferred:
                return code
        for row in rows:
            code = str(row.get("upcode") or "").strip()
            if re.fullmatch(r"\d{3}", code):
                return code
        raise ValueError("t8424에서 3자리 업종코드를 찾지 못했습니다.")

    @staticmethod
    def _emit(
        callback: ProgressCallback | None,
        step: int,
        total: int,
        label: str,
        result: TrQualificationResult | None,
    ) -> None:
        if callback is not None:
            callback(step, total, label, result)
