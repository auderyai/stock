from __future__ import annotations

from collections.abc import Callable

import pandas as pd


ScreenRule = Callable[[pd.DataFrame], pd.Series]


def _latest(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        raise ValueError("스크리닝할 자료가 없습니다.")
    return frame.iloc[-1]


def evaluate_screens(frame: pd.DataFrame) -> dict[str, bool]:
    """Evaluate common screens from an indicator frame without storing results."""

    row = _latest(frame)
    previous = frame.iloc[-2] if len(frame) > 1 else row
    return {
        "ema_bullish_alignment": bool(row.get("ema_alignment", 0) == 1),
        "close_above_ema5": bool(row.get("close_above_ema5", False)),
        "bollinger_breakout": bool(row.get("bollinger_breakout", False)),
        "volume_surge_20": bool(row.get("volume_surge_20", False)),
        "new_52week_high": bool(
            pd.notna(row.get("high_52w")) and row.get("close_price", 0) >= row.get("high_52w", float("inf"))
        ),
        "macd_bullish_cross": bool(
            row.get("macd", float("nan")) > row.get("macd_signal", float("nan"))
            and previous.get("macd", float("nan")) <= previous.get("macd_signal", float("nan"))
        ),
        "rsi_oversold": bool(pd.notna(row.get("rsi_14")) and row.get("rsi_14", 100) < 30),
        "rsi_overbought": bool(pd.notna(row.get("rsi_14")) and row.get("rsi_14", 0) > 70),
    }
