from __future__ import annotations

import datetime as dt

import pandas as pd

from krx_research.data_engine.postgresql import BaseDataRepository


class InvestorFlowRepository:
    """PostgreSQL access for the investor dashboard."""

    def __init__(self, settings) -> None:
        self._settings = settings

    def load_period(self, start: dt.date, end: dt.date):
        with BaseDataRepository(self._settings) as repository:
            row = repository.conn.execute(
                "SELECT to_regclass('market_core.ls_investor_t1702_checkpoint') AS table_name"
            ).fetchone()
            actual_days = () if not row or not row["table_name"] else tuple(
                item["trade_date"]
                for item in repository.conn.execute(
                    "SELECT DISTINCT trade_date FROM market_core.ls_investor_t1702_checkpoint "
                    "WHERE exchange_code='K' AND trade_date BETWEEN %s AND %s ORDER BY trade_date",
                    (start, end),
                ).fetchall()
            )
            prices = repository.get_market_ohlcv(start, end)
            market_days = () if prices.empty else tuple(
                sorted({pd.Timestamp(value).date() for value in prices["trade_date"].dropna()})
            )
            flows, used_days = [], []
            for day in actual_days or market_days:
                flow = repository.get_market_investor_flow(day)
                if flow is not None and not flow.empty:
                    flows.append(flow)
                    used_days.append(day)
            return flows, tuple(used_days), market_days, repository.get_security_master_frame(), prices
