from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from krx_research.data_engine.investor import FOREIGN_MEMBERS, INSTITUTION_MEMBERS
from krx_research.qt.models.investor_dashboard import InvestorDashboardData
from krx_research.ui.data import build_investor_flow_rows

INVESTOR_CODES = {
    "foreign": FOREIGN_MEMBERS,
    "institution": INSTITUTION_MEMBERS,
    "individual": ("INDIVIDUAL",),
}


class InvestorDashboardService:
    """Qt-free service for period investor-flow aggregation."""

    def __init__(self, repository: Any):
        self._repository = repository

    def load(self, start: dt.date, end: dt.date, *, top_n: int = 10) -> InvestorDashboardData:
        if int(top_n) < 1 or int(top_n) > 5000:
            raise ValueError("순위는 1 ~ 5000 사이로 입력하십시오.")
        if start > end:
            raise ValueError(f"시작일 {start}은 종료일 {end}보다 늦습니다.")
        frames, used_days, market_days, master, price_history = self._repository.load_period(start, end)
        if not frames:
            raise ValueError(f"{start} ~ {end} 구간에 조회 가능한 LS 수급 자료가 없습니다.")
        flow = pd.concat(frames, ignore_index=True)
        flow.attrs.update(frames[-1].attrs)
        if master.empty:
            raise ValueError("종목 기본자료가 비어 있습니다.")
        if price_history.empty:
            raise ValueError(f"{start} ~ {end} 일봉 자료가 없습니다.")
        prices = price_history.sort_values(["stock_code", "trade_date"]).drop_duplicates("stock_code", keep="last").reset_index(drop=True)
        securities = master[["stock_code", "market", "stock_name"]].copy()
        securities["market"] = securities["market"].astype("string").str.upper().str.strip()
        securities = securities.drop_duplicates("stock_code")
        facts = flow.merge(securities, on="stock_code", how="inner", validate="m:1")
        facts = facts.loc[
            facts["market"].isin(("KOSPI", "KOSDAQ"))
            & ~facts["stock_name"].astype("string").fillna("").str.contains("스팩|SPAC", case=False)
        ].copy()
        for column in ("buy_value", "sell_value"):
            facts[column] = pd.to_numeric(facts[column], errors="coerce")
        totals: dict[tuple[str, str], int] = {}
        counts = {
            market: int(facts.loc[facts["market"].eq(market), "stock_code"].nunique())
            for market in ("KOSPI", "KOSDAQ")
        }
        rankings: dict[tuple[str, str, str], pd.DataFrame] = {}
        for market in ("KOSPI", "KOSDAQ"):
            for investor, codes in INVESTOR_CODES.items():
                subset = facts.loc[facts["market"].eq(market) & facts["investor_type"].isin(codes)]
                totals[(market, investor)] = int(subset["buy_value"].sum() - subset["sell_value"].sum())
                for direction in ("buy", "sell"):
                    screen_type = f"{market.lower()}_{investor}_net_{direction}"
                    rankings[(market, investor, direction)] = build_investor_flow_rows(flow, master, prices, screen_type, limit=int(top_n))
        return InvestorDashboardData(
            requested_start=start,
            requested_end=end,
            actual_days=used_days,
            market_days=market_days,
            market_totals=totals,
            market_counts=counts,
            rankings=rankings,
        )
