"""Validated NXT daily-history imports from user-provided CSV/Excel files."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import re

import numpy as np
import pandas as pd
from pandas import DataFrame


NXT_LAUNCH_DATE = dt.date(2025, 3, 4)

_ALIASES = {
    "stock_code": ("stock_code", "ticker", "code", "종목코드", "단축코드", "종목 코드"),
    "trade_date": ("trade_date", "date", "일자", "날짜", "거래일", "기준일"),
    "open_price": ("open_price", "open", "시가"),
    "high_price": ("high_price", "high", "고가"),
    "low_price": ("low_price", "low", "저가"),
    "close_price": ("close_price", "close", "종가", "현재가"),
    "volume": ("volume", "거래량", "누적거래량"),
    "amount": ("amount", "trade_value", "value", "거래대금", "누적거래대금"),
}
_REQUIRED = (
    "stock_code", "trade_date", "open_price", "high_price", "low_price",
    "close_price", "volume",
)


def _key(value: object) -> str:
    return re.sub(r"[\s_()\[\]./-]+", "", str(value)).casefold()


def _column_map(columns: list[object]) -> dict[object, str]:
    keyed = {_key(column): column for column in columns}
    result: dict[object, str] = {}
    for canonical, aliases in _ALIASES.items():
        match = next((keyed.get(_key(alias)) for alias in aliases if _key(alias) in keyed), None)
        if match is not None:
            result[match] = canonical
    return result


def read_nxt_history_file(path: str | Path) -> DataFrame:
    """Read all compatible sheets and return strictly validated NXT bars."""

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"NXT 자료 파일을 찾을 수 없습니다: {source}")
    suffix = source.suffix.casefold()
    if suffix == ".csv":
        try:
            candidates = {"CSV": pd.read_csv(source, encoding="utf-8-sig")}
        except UnicodeDecodeError:
            candidates = {"CSV": pd.read_csv(source, encoding="cp949")}
    elif suffix in {".xlsx", ".xlsm", ".xls"}:
        candidates = pd.read_excel(source, sheet_name=None)
    else:
        raise ValueError("NXT 자료는 CSV, XLSX, XLSM 또는 XLS 파일이어야 합니다.")

    frames: list[DataFrame] = []
    errors: list[str] = []
    for sheet_name, raw in candidates.items():
        mapping = _column_map(list(raw.columns))
        missing = [column for column in _REQUIRED if column not in mapping.values()]
        if missing:
            errors.append(f"{sheet_name}: {', '.join(missing)}")
            continue
        frame = raw.rename(columns=mapping).copy()
        if "amount" not in frame:
            frame["amount"] = pd.NA
        frame = frame[[*_REQUIRED, "amount"]]
        frame["_sheet"] = str(sheet_name)
        frames.append(frame)
    if not frames:
        detail = "; ".join(errors) if errors else "읽을 수 있는 시트가 없습니다."
        raise ValueError(f"NXT 일봉 필수 열을 찾지 못했습니다. {detail}")

    result = pd.concat(frames, ignore_index=True)
    result["stock_code"] = (
        result["stock_code"].astype("string").str.strip().str.upper().str.removeprefix("A")
    )
    result["stock_code"] = result["stock_code"].str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.normalize()
    for column in ("open_price", "high_price", "low_price", "close_price", "volume", "amount"):
        result[column] = pd.to_numeric(
            result[column].astype("string").str.replace(",", "", regex=False),
            errors="coerce",
        )
    invalid = (
        result["stock_code"].isna()
        | result["trade_date"].isna()
        | result[list(_REQUIRED[2:])].isna().any(axis=1)
        | result[["open_price", "high_price", "low_price", "close_price"]].le(0).any(axis=1)
        | result["volume"].lt(0)
        | (result["amount"].notna() & result["amount"].lt(0))
        | result["high_price"].lt(result[["open_price", "low_price", "close_price"]].max(axis=1))
        | result["low_price"].gt(result[["open_price", "high_price", "close_price"]].min(axis=1))
    )
    if invalid.any():
        sample = ", ".join(str(index + 2) for index in result.index[invalid][:10])
        raise ValueError(f"NXT 자료에 잘못된 행이 {int(invalid.sum()):,}개 있습니다. 행 예: {sample}")
    before_launch = result["trade_date"].dt.date.lt(NXT_LAUNCH_DATE)
    future = result["trade_date"].dt.date.gt(dt.date.today())
    if before_launch.any() or future.any():
        raise ValueError(
            f"NXT 거래일은 {NXT_LAUNCH_DATE.isoformat()}부터 오늘까지여야 합니다."
        )

    keys = ["stock_code", "trade_date"]
    duplicate = result.duplicated(keys, keep=False)
    if duplicate.any():
        compare_columns = ["open_price", "high_price", "low_price", "close_price", "volume", "amount"]
        conflicting = result.loc[duplicate].groupby(keys, dropna=False)[compare_columns].nunique(dropna=False).max(axis=1).gt(1)
        if conflicting.any():
            code, date = conflicting.index[0]
            raise ValueError(f"같은 종목·거래일에 서로 다른 값이 있습니다: {code} {date:%Y-%m-%d}")
        result = result.drop_duplicates(keys, keep="last")

    result["volume"] = result["volume"].round().astype("int64")
    result["amount"] = result["amount"].round().astype("Int64")
    result["source"] = "NXT:USER_FILE"
    result = result.drop(columns="_sheet").sort_values(keys, ignore_index=True)
    return result


def summarize_nxt_history(frame: DataFrame) -> dict[str, object]:
    if frame.empty:
        raise ValueError("NXT 일봉 자료가 비어 있습니다.")
    dates = pd.to_datetime(frame["trade_date"])
    return {
        "rows": len(frame),
        "tickers": int(frame["stock_code"].nunique()),
        "dates": int(dates.nunique()),
        "start_date": dates.min().date(),
        "end_date": dates.max().date(),
    }


__all__ = ["NXT_LAUNCH_DATE", "read_nxt_history_file", "summarize_nxt_history"]
