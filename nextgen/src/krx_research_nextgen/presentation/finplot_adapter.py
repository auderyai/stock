from __future__ import annotations

import pandas as pd
import finplot as fplt

from krx_research_nextgen.models.chart_data import ChartBundle


class FinplotChartAdapter:
    """Finplot presentation adapter.

    Responsibilities:
    - Render prepared chart data.
    - Do not access the database.
    - Do not calculate indicators.
    """

    def render(self, bundle: ChartBundle) -> None:
        df = bundle.frame.copy()
        self._validate(df)

        if not isinstance(df.index, pd.DatetimeIndex):
            raise TypeError("FinplotChartAdapter requires a DatetimeIndex")

        ax_price, ax_volume, ax_rsi, ax_macd = fplt.create_plot(
            bundle.symbol,
            rows=4,
        )

        fplt.candlestick_ochl(
            df[["open", "close", "high", "low"]],
            ax=ax_price,
        )

        fplt.plot(df["bb_upper"], ax=ax_price, legend="BB upper")
        fplt.plot(df["bb_mid"], ax=ax_price, legend="BB mid")
        fplt.plot(df["bb_lower"], ax=ax_price, legend="BB lower")

        fplt.volume_ocv(
            df[["open", "close", "volume"]],
            ax=ax_volume,
        )

        fplt.plot(df["rsi"], ax=ax_rsi, legend="RSI")
        ax_rsi.addLine(y=70)
        ax_rsi.addLine(y=30)

        fplt.plot(df["macd"], ax=ax_macd, legend="MACD")
        fplt.plot(df["macd_signal"], ax=ax_macd, legend="Signal")
        fplt.plot(df["macd_hist"], ax=ax_macd, legend="Histogram")

        fplt.show()

    @staticmethod
    def _validate(df: pd.DataFrame) -> None:
        required = {
            "open", "high", "low", "close", "volume",
            "rsi", "macd", "macd_signal", "macd_hist",
            "bb_upper", "bb_mid", "bb_lower",
        }
        missing = sorted(required.difference(df.columns))
        if missing:
            raise ValueError(f"render data missing columns: {missing}")
