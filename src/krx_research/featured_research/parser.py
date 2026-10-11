"""Normalize recurring daily featured-stock spreadsheets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re

import pandas as pd


_ALIASES = {
    "report_date": ("DATE", "날짜", "기준일", "일자", "거래일", "작성일"),
    "ticker": ("종목코드", "코드"),
    "stock_name": ("종목", "종목명"),
    "return_rate": ("등락률", "등락율", "이미지 기준 등락률"),
    "trading_value_eok": ("거래대금(억)", "거래대금(억원)", "거래대금"),
    "theme_name": ("테마", "테마명", "테마 분류"),
    "reason": ("사유", "상승 사유", "상승사유"),
}


@dataclass(frozen=True, slots=True)
class FeaturedRow:
    source_row: int
    report_date: date
    ticker: str | None
    stock_name: str
    return_pct: float | None
    source_trading_value_eok: float | None
    theme_name: str | None
    reason: str
    raw_data: dict[str, object]


@dataclass(frozen=True, slots=True)
class ParsedFeaturedSpreadsheet:
    path: Path
    file_name: str
    file_sha256: str
    sheet_name: str
    report_date: date
    rows: tuple[FeaturedRow, ...]


def _label(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def _find_column(columns: list[str], canonical: str, *, required: bool) -> str | None:
    labels = {_label(column).casefold(): column for column in columns}
    for alias in _ALIASES[canonical]:
        found = labels.get(_label(alias).casefold())
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


def _date(value: object) -> date:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return pd.to_datetime(value, unit="D", origin="1899-12-30").date()
    return pd.Timestamp(value).date()


def _date_column(frame: pd.DataFrame) -> str | None:
    named = _find_column(list(frame.columns), "report_date", required=False)
    if named:
        return named
    # Daily exports such as '9월21일 특징주.xlsx' have a blank first header
    # while the actual date cells are Excel datetime values.
    for column in frame.columns:
        if not (not str(column).strip() or str(column).startswith("Unnamed:")):
            continue
        values = frame[column].dropna()
        if len(values) and all(
            isinstance(value, (date, pd.Timestamp)) or
            (isinstance(value, str) and bool(re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", value.strip())))
            for value in values
        ):
            return str(column)
    return None


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
    normalized = number if "%" in str(value) or abs(number) > 1.5 else number * 100.0
    return round(normalized, 10)


def _json_value(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        value = item()
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def parse_featured_spreadsheet(path: str | Path) -> ParsedFeaturedSpreadsheet:
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError(".xlsx 또는 .xlsm 파일만 등록할 수 있습니다.")
    if not source.is_file():
        raise FileNotFoundError(source)

    selected: tuple[str, pd.DataFrame] | None = None
    errors: list[str] = []
    required = ("stock_name", "return_rate", "reason")
    with pd.ExcelFile(source, engine="openpyxl") as workbook:
        for sheet_name in workbook.sheet_names:
            frame = pd.read_excel(workbook, sheet_name=sheet_name, dtype=object)
            frame.columns = [_label(item) for item in frame.columns]
            try:
                for canonical in required:
                    _find_column(list(frame.columns), canonical, required=True)
                if _date_column(frame) is None:
                    _find_column(list(frame.columns), "report_date", required=True)
            except ValueError as error:
                errors.append(f"{sheet_name}: {error}")
                continue
            selected = sheet_name, frame
            break
    if selected is None:
        raise ValueError("지원되는 특징주 자료 시트를 찾지 못했습니다. " + "; ".join(errors))

    sheet_name, frame = selected
    columns = list(frame.columns)
    mapping = {
        key: _date_column(frame) if key == "report_date" else
        _find_column(columns, key, required=key in required)
        for key in _ALIASES
    }
    rows: list[FeaturedRow] = []
    dates: set[date] = set()
    for index, record in frame.iterrows():
        if all(pd.isna(value) for value in record.tolist()):
            continue
        source_row = int(index) + 2
        try:
            report_date = _date(record[mapping["report_date"]])
            stock_name = _label(record[mapping["stock_name"]])
            reason = _label(record[mapping["reason"]])
            ticker_column = mapping["ticker"]
            theme_column = mapping["theme_name"]
            ticker = _ticker(record[ticker_column]) if ticker_column else None
            theme = _label(record[theme_column]) if theme_column and not pd.isna(record[theme_column]) else None
        except Exception as error:
            raise ValueError(f"{sheet_name} {source_row}행: {error}") from error
        if not stock_name or not reason:
            raise ValueError(f"{sheet_name} {source_row}행: 종목명 또는 사유가 비어 있습니다.")
        dates.add(report_date)
        rows.append(
            FeaturedRow(
                source_row=source_row,
                report_date=report_date,
                ticker=ticker,
                stock_name=stock_name,
                return_pct=_return_pct(record[mapping["return_rate"]]),
                source_trading_value_eok=(
                    _number(record[mapping["trading_value_eok"]])
                    if mapping["trading_value_eok"] else None
                ),
                theme_name=theme,
                reason=reason,
                raw_data={str(key): _json_value(value) for key, value in record.items()},
            )
        )
    if not rows:
        raise ValueError("등록할 자료 행이 없습니다.")
    if len(dates) != 1:
        rendered = ", ".join(sorted(item.isoformat() for item in dates))
        raise ValueError(f"한 파일에는 한 기준일만 있어야 합니다: {rendered}")
    return ParsedFeaturedSpreadsheet(
        path=source,
        file_name=source.name,
        file_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        sheet_name=sheet_name,
        report_date=next(iter(dates)),
        rows=tuple(rows),
    )


def raw_json_text(row: FeaturedRow) -> str:
    return json.dumps(row.raw_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["FeaturedRow", "ParsedFeaturedSpreadsheet", "parse_featured_spreadsheet", "raw_json_text"]
