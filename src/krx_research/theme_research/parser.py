"""Normalize daily hot-theme XLSX files without depending on one template."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd


_ALIASES = {
    "report_date": ("DATE", "날짜", "기준일"),
    "ticker": ("종목코드", "코드"),
    "stock_name": ("종목명", "종목"),
    "return_rate": ("이미지 기준 등락률", "등락률", "등락율"),
    "source_trading_value_eok": ("거래대금(억)", "거래대금(억원)", "거래대금"),
    "theme_name": ("테마", "테마명", "테마 분류"),
    "reason": ("상승 사유", "사유", "상승사유", "테마별 주요 이슈 및 사유"),
}


@dataclass(frozen=True, slots=True)
class ThemeRow:
    source_row: int
    report_date: date
    ticker: str | None
    stock_name: str
    return_pct: float | None
    source_trading_value_eok: float | None
    theme_name: str
    reason: str
    raw_data: dict[str, object]


@dataclass(frozen=True, slots=True)
class ParsedSpreadsheet:
    path: Path
    file_name: str
    file_sha256: str
    sheet_name: str
    report_date: date
    rows: tuple[ThemeRow, ...]


def _label(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def _find_column(columns: list[str], canonical: str, *, required: bool) -> str | None:
    by_label = {_label(column).casefold(): column for column in columns}
    for alias in _ALIASES[canonical]:
        found = by_label.get(_label(alias).casefold())
        if found is not None:
            return found
    if required:
        raise ValueError(
            f"필수 열을 찾을 수 없습니다: {canonical} "
            f"(허용: {', '.join(_ALIASES[canonical])})"
        )
    return None


def _ticker(value: object) -> str | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    text = str(value).strip().upper()
    if text == "주외종목":
        return None
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    if not re.fullmatch(r"[0-9A-Z]{6}", text):
        raise ValueError(f"잘못된 종목코드: {value!r}")
    return text


def _number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "—", "N/A", "nan"}:
        return None
    return float(text.rstrip("%"))


def _return_pct(value: object) -> float | None:
    number = _number(value)
    if number is None:
        return None
    text = str(value).strip()
    return number if "%" in text or abs(number) > 1.5 else number * 100.0


def _json_value(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        value = item()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def parse_theme_spreadsheet(path: str | Path) -> ParsedSpreadsheet:
    """Read one daily XLSX and normalize supported Korean header variants."""

    source = Path(path).expanduser().resolve()
    if source.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError(".xlsx 또는 .xlsm 파일만 등록할 수 있습니다.")
    if not source.is_file():
        raise FileNotFoundError(source)

    errors: list[str] = []
    selected: tuple[str, pd.DataFrame] | None = None
    with pd.ExcelFile(source, engine="openpyxl") as workbook:
        for sheet_name in workbook.sheet_names:
            frame = pd.read_excel(workbook, sheet_name=sheet_name, dtype=object)
            columns = [_label(item) for item in frame.columns]
            frame.columns = columns
            try:
                for canonical in ("report_date", "stock_name", "theme_name", "reason"):
                    _find_column(columns, canonical, required=True)
            except ValueError as error:
                errors.append(f"{sheet_name}: {error}")
                continue
            selected = sheet_name, frame
            break
    if selected is None:
        raise ValueError("지원되는 테마 자료 시트를 찾지 못했습니다. " + "; ".join(errors))

    sheet_name, frame = selected
    columns = list(frame.columns)
    mapping = {
        key: _find_column(columns, key, required=key not in {"ticker", "return_rate", "source_trading_value_eok"})
        for key in _ALIASES
    }
    rows: list[ThemeRow] = []
    report_dates: set[date] = set()
    for index, record in frame.iterrows():
        if all(pd.isna(value) for value in record.tolist()):
            continue
        source_row = int(index) + 2
        try:
            parsed_date = pd.Timestamp(record[mapping["report_date"]]).date()
            code = _ticker(record[mapping["ticker"]]) if mapping["ticker"] else None
            name = _label(record[mapping["stock_name"]])
            theme = _label(record[mapping["theme_name"]])
            reason = _label(record[mapping["reason"]])
        except Exception as error:
            raise ValueError(f"{sheet_name} {source_row}행: {error}") from error
        if not name or not theme:
            raise ValueError(f"{sheet_name} {source_row}행: 종목명 또는 테마가 비어 있습니다.")
        report_dates.add(parsed_date)
        return_column = mapping["return_rate"]
        value_column = mapping["source_trading_value_eok"]
        rows.append(
            ThemeRow(
                source_row=source_row,
                report_date=parsed_date,
                ticker=code,
                stock_name=name,
                return_pct=_return_pct(record[return_column]) if return_column else None,
                source_trading_value_eok=_number(record[value_column]) if value_column else None,
                theme_name=theme,
                reason=reason,
                raw_data={str(key): _json_value(value) for key, value in record.items()},
            )
        )
    if not rows:
        raise ValueError("등록할 자료 행이 없습니다.")
    if len(report_dates) != 1:
        rendered = ", ".join(sorted(item.isoformat() for item in report_dates))
        raise ValueError(f"한 파일에는 한 기준일만 있어야 합니다: {rendered}")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return ParsedSpreadsheet(
        path=source,
        file_name=source.name,
        file_sha256=digest,
        sheet_name=sheet_name,
        report_date=next(iter(report_dates)),
        rows=tuple(rows),
    )


def raw_json_text(row: ThemeRow) -> str:
    return json.dumps(row.raw_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["ParsedSpreadsheet", "ThemeRow", "parse_theme_spreadsheet", "raw_json_text"]
