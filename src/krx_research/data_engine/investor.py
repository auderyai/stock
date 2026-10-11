from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from .timeframes import Timeframe


INVESTOR_LABELS: dict[str, str] = {
    "FINANCIAL_INVESTMENT": "금융투자",
    "INSURANCE": "보험",
    "INVESTMENT_TRUST": "투신",
    "PRIVATE_FUND": "사모펀드",
    "BANK": "은행",
    "OTHER_FINANCE": "종금·기타금융",
    "PENSION": "연기금",
    "OTHER_CORPORATION": "기타법인",
    "INDIVIDUAL": "개인",
    "FOREIGN": "외국인",
    "OTHER_FOREIGN": "기타외국인",
    "INSTITUTION_TOTAL": "기관합계",
    "FOREIGN_TOTAL": "외국인합계",
}

PROVIDER_TO_CODE: dict[str, str] = {
    "금융투자": "FINANCIAL_INVESTMENT",
    "보험": "INSURANCE",
    "투신": "INVESTMENT_TRUST",
    "사모": "PRIVATE_FUND",
    "사모펀드": "PRIVATE_FUND",
    "은행": "BANK",
    "종금": "OTHER_FINANCE",
    "기타금융": "OTHER_FINANCE",
    "연기금": "PENSION",
    "연기금 등": "PENSION",
    "기타법인": "OTHER_CORPORATION",
    "개인": "INDIVIDUAL",
    "외국인": "FOREIGN",
    "기관합계": "INSTITUTION_TOTAL",
    "외국인합계": "FOREIGN_TOTAL",
    "기타외국인": "OTHER_FOREIGN",
}

LEAF_INVESTORS = tuple(code for code in INVESTOR_LABELS if not code.endswith("_TOTAL"))
INSTITUTION_MEMBERS = (
    "FINANCIAL_INVESTMENT",
    "INSURANCE",
    "INVESTMENT_TRUST",
    "PRIVATE_FUND",
    "BANK",
    "OTHER_FINANCE",
    "PENSION",
)
FOREIGN_MEMBERS = ("FOREIGN", "OTHER_FOREIGN")
VALUE_COLUMNS = ("buy_volume", "sell_volume", "buy_value", "sell_value")


def normalize_investor_code(value: str) -> str:
    normalized = str(value).strip()
    upper = normalized.upper()
    if upper in INVESTOR_LABELS:
        return upper
    try:
        return PROVIDER_TO_CODE[normalized]
    except KeyError as exc:
        raise ValueError(f"지원하지 않는 투자자 구분: {value!r}") from exc


def _period_key(index: pd.DatetimeIndex, timeframe: Timeframe) -> pd.PeriodIndex:
    return {
        Timeframe.WEEKLY: index.to_period("W-FRI"),
        Timeframe.MONTHLY: index.to_period("M"),
        Timeframe.QUARTERLY: index.to_period("Q-DEC"),
        Timeframe.YEARLY: index.to_period("Y-DEC"),
    }[timeframe]


def _append_total(frame: pd.DataFrame, code: str, members: Iterable[str]) -> pd.DataFrame:
    selected = frame.loc[frame["investor_type"].isin(tuple(members))]
    if selected.empty:
        return frame
    keys = ["trade_date"]
    if "stock_code" in frame.columns:
        keys.insert(0, "stock_code")
    total = selected.groupby(keys, as_index=False, observed=True)[list(VALUE_COLUMNS)].sum()
    total["investor_type"] = code
    return pd.concat([frame, total], ignore_index=True)


def aggregate_investor_flow(
    frame: pd.DataFrame,
    timeframe: Timeframe | str = Timeframe.DAILY,
    *,
    include_totals: bool = True,
) -> pd.DataFrame:
    """Aggregate stored buy/sell facts and derive net/totals on demand."""

    period = Timeframe.parse(timeframe)
    output_columns = ["trade_date", "investor_type", *VALUE_COLUMNS, "net_volume", "net_value"]
    if frame is None or frame.empty:
        return pd.DataFrame(columns=output_columns)
    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    result = result.loc[result["trade_date"].notna()]
    result["investor_type"] = result["investor_type"].map(normalize_investor_code)
    for column in VALUE_COLUMNS:
        if column not in result.columns:
            result[column] = 0
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)

    keys = ["investor_type"]
    if "stock_code" in result.columns:
        keys.insert(0, "stock_code")
    if period is Timeframe.DAILY:
        keys.insert(-1 if keys[-1] == "investor_type" else len(keys), "trade_date")
        # Explicit keys are clearer than relying on the insertion above.
        keys = (["stock_code"] if "stock_code" in result.columns else []) + ["trade_date", "investor_type"]
        result = result.groupby(keys, as_index=False, observed=True)[list(VALUE_COLUMNS)].sum()
    else:
        result["_period"] = _period_key(pd.DatetimeIndex(result["trade_date"]), period)
        group_keys = (["stock_code"] if "stock_code" in result.columns else []) + ["_period", "investor_type"]
        values = result.groupby(group_keys, as_index=False, observed=True)[list(VALUE_COLUMNS)].sum()
        last_dates = result.groupby(
            (["stock_code"] if "stock_code" in result.columns else []) + ["_period"],
            as_index=False,
            observed=True,
        )["trade_date"].max()
        result = values.merge(last_dates, on=(["stock_code"] if "stock_code" in result.columns else []) + ["_period"])
        result = result.drop(columns="_period")

    if include_totals:
        result = _append_total(result, "INSTITUTION_TOTAL", INSTITUTION_MEMBERS)
        result = _append_total(result, "FOREIGN_TOTAL", FOREIGN_MEMBERS)
    result["net_volume"] = result["buy_volume"] - result["sell_volume"]
    result["net_value"] = result["buy_value"] - result["sell_value"]
    result["investor_name"] = result["investor_type"].map(INVESTOR_LABELS)
    sort_columns = (["stock_code"] if "stock_code" in result.columns else []) + ["trade_date", "investor_type"]
    return result.sort_values(sort_columns, ignore_index=True)


def pivot_net_flow(frame: pd.DataFrame, unit: str = "value") -> pd.DataFrame:
    column = {"value": "net_value", "volume": "net_volume"}.get(unit.lower())
    if column is None:
        raise ValueError("unit은 value 또는 volume이어야 합니다.")
    if frame.empty:
        return pd.DataFrame()
    return frame.pivot_table(
        index="trade_date",
        columns="investor_type",
        values=column,
        aggfunc="sum",
        fill_value=0,
    ).sort_index()
