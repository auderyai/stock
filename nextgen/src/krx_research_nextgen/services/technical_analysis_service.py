from __future__ import annotations

import numpy as np
import pandas as pd
from ta.trend import MACD

from krx_research_nextgen.models.chart_data import IndicatorConfig


class TechnicalAnalysisService:
    """GUI-free technical-analysis service.

    Rules:
    - RSI and its signal use the user-approved exponential moving averages.
    - All numeric outputs preserve float dtype.
    """

    REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")

    def enrich(
        self,
        frame: pd.DataFrame,
        config: IndicatorConfig | None = None,
    ) -> pd.DataFrame:
        cfg = config or IndicatorConfig()
        self._validate(frame)
        df = frame.copy()

        close = pd.to_numeric(df["close"], errors="coerce").astype("float64")

        df["rsi"] = self._exponential_rsi(close, float(cfg.rsi_period))
        df["rsi_signal"] = df["rsi"].ewm(
            span=int(cfg.rsi_signal), adjust=False, min_periods=int(cfg.rsi_signal)
        ).mean()

        for window in cfg.ema_windows:
            df[f"ema_{window}"] = close.ewm(span=window, adjust=False).mean()

        macd = MACD(
            close=close,
            window_slow=int(cfg.macd_slow),
            window_fast=int(cfg.macd_fast),
            window_sign=int(cfg.macd_signal),
            fillna=False,
        )
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_hist"] = macd.macd_diff()

        window = int(cfg.bollinger_window)
        df["bb_mid"] = close.ewm(span=window, adjust=False, min_periods=window).mean()
        deviation = close.rolling(window, min_periods=window).std(ddof=0)
        df["bb_upper"] = df["bb_mid"] + float(cfg.bollinger_std) * deviation
        df["bb_lower"] = df["bb_mid"] - float(cfg.bollinger_std) * deviation

        high = pd.to_numeric(df["high"], errors="coerce").astype("float64")
        low = pd.to_numeric(df["low"], errors="coerce").astype("float64")
        lowest = low.rolling(int(cfg.stochastic_window), min_periods=int(cfg.stochastic_window)).min()
        highest = high.rolling(int(cfg.stochastic_window), min_periods=int(cfg.stochastic_window)).max()
        fast_k = (close - lowest) / (highest - lowest).replace(0.0, np.nan) * 100.0
        df["stoch_slow_k"] = fast_k.ewm(
            span=int(cfg.stochastic_smooth), adjust=False,
            min_periods=int(cfg.stochastic_smooth),
        ).mean()
        df["stoch_slow_d"] = df["stoch_slow_k"].ewm(
            span=int(cfg.stochastic_signal), adjust=False,
            min_periods=int(cfg.stochastic_signal),
        ).mean()

        return df

    def _validate(self, frame: pd.DataFrame) -> None:
        missing = [c for c in self.REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            raise ValueError(f"missing OHLCV columns: {missing}")
        if frame.empty:
            raise ValueError("OHLCV frame is empty")

    @staticmethod
    def _exponential_rsi(close: pd.Series, period: float) -> pd.Series:
        if not np.isfinite(period) or period <= 1:
            raise ValueError("RSI period must be > 1")

        close = pd.to_numeric(close, errors="coerce").astype("float64")
        delta = close.diff()

        gains = delta.clip(lower=0.0).astype("float64")
        losses = (-delta.clip(upper=0.0)).astype("float64")

        alpha = 2.0 / (float(period) + 1.0)
        min_periods = max(2, int(period))

        avg_gain = gains.ewm(
            alpha=alpha,
            adjust=False,
            min_periods=min_periods,
        ).mean().astype("float64")

        avg_loss = losses.ewm(
            alpha=alpha,
            adjust=False,
            min_periods=min_periods,
        ).mean().astype("float64")

        # Keep the entire calculation in float dtype.
        # Using pd.NA here would coerce the Series to object dtype.
        loss_safe = avg_loss.mask(avg_loss == 0.0, np.nan)
        rs = avg_gain / loss_safe
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # Edge cases:
        # positive gain + zero loss => RSI 100
        # zero gain + positive loss => RSI 0
        # zero gain + zero loss => neutral RSI 50
        zero_loss = avg_loss == 0.0
        zero_gain = avg_gain == 0.0
        rsi = rsi.mask(zero_loss & ~zero_gain, 100.0)
        rsi = rsi.mask(~zero_loss & zero_gain, 0.0)
        rsi = rsi.mask(zero_loss & zero_gain, 50.0)

        return pd.Series(
            np.asarray(rsi, dtype="float64"),
            index=close.index,
            name="rsi",
            dtype="float64",
        )
