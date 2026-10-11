from __future__ import annotations

import math
import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD
from ta.volatility import BollingerBands

from krx_research_nextgen.models.chart_data import IndicatorConfig


class TechnicalAnalysisService:
    """GUI-free technical-analysis service.

    Rules:
    - Standard integer windows use the `ta` library.
    - Fractional RSI periods use a Wilder-style EWM implementation.
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

        if float(cfg.rsi_period).is_integer():
            df["rsi"] = RSIIndicator(
                close=close,
                window=int(cfg.rsi_period),
                fillna=False,
            ).rsi()
        else:
            df["rsi"] = self._fractional_rsi(close, float(cfg.rsi_period))
        df["rsi_signal"] = df["rsi"].rolling(9).mean()

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

        bb = BollingerBands(
            close=close,
            window=int(cfg.bollinger_window),
            window_dev=float(cfg.bollinger_std),
            fillna=False,
        )
        df["bb_mid"] = bb.bollinger_mavg()
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()

        stochastic = StochasticOscillator(
            high=pd.to_numeric(df["high"], errors="coerce").astype("float64"),
            low=pd.to_numeric(df["low"], errors="coerce").astype("float64"),
            close=close,
            window=int(cfg.stochastic_window),
            smooth_window=int(cfg.stochastic_smooth),
            fillna=False,
        )
        df["stoch_slow_k"] = stochastic.stoch_signal()
        df["stoch_slow_d"] = df["stoch_slow_k"].rolling(
            int(cfg.stochastic_smooth)
        ).mean()

        return df

    def _validate(self, frame: pd.DataFrame) -> None:
        missing = [c for c in self.REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            raise ValueError(f"missing OHLCV columns: {missing}")
        if frame.empty:
            raise ValueError("OHLCV frame is empty")

    @staticmethod
    def _fractional_rsi(close: pd.Series, period: float) -> pd.Series:
        if not math.isfinite(period) or period <= 1:
            raise ValueError("fractional RSI period must be > 1")

        close = pd.to_numeric(close, errors="coerce").astype("float64")
        delta = close.diff()

        gains = delta.clip(lower=0.0).astype("float64")
        losses = (-delta.clip(upper=0.0)).astype("float64")

        alpha = 1.0 / float(period)
        min_periods = max(2, int(math.floor(period)))

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
