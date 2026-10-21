from __future__ import annotations
from krx_research.analytics.classic_strategies import assess_classic_strategies
from krx_research.qt.services.ports import ChartDataPort


class ChartService:
    """Chart application service; data loading and rule assessments are Qt-free."""
    def __init__(self, data: ChartDataPort):
        self._data = data

    def resolve(self, ticker_or_name: str) -> str:
        return self._data.resolve_ticker(ticker_or_name)

    def load(self, ticker_or_name: str, quote_venue: str):
        code = self.resolve(ticker_or_name)
        return self._data.load_chart(
            code,
            timeframes=("D", "W", "M", "Q", "Y"),
            include_investor=True,
            quote_venue=quote_venue,
        )

    @staticmethod
    def assess_strategies(dataset):
        try:
            return assess_classic_strategies(dataset.daily, dataset.weekly)
        except Exception:
            return ()
