"""Typed display choices for the workstation chart window."""

from __future__ import annotations

from dataclasses import dataclass

from .on_demand import TIMEFRAME_LABELS


LABEL_TO_TIMEFRAME = {label: key for key, label in TIMEFRAME_LABELS.items()}


@dataclass(frozen=True)
class ChartDisplayOptions:
    timeframe: str = "D"
    show_volume: bool = True
    show_rsi: bool = True
    show_macd: bool = True
    show_stochastic: bool = True
    show_institution: bool = False
    show_foreign: bool = False
    show_individual: bool = False

    def validate(self) -> "ChartDisplayOptions":
        key = str(self.timeframe).strip().upper()
        if key not in TIMEFRAME_LABELS:
            raise ValueError(f"지원하지 않는 봉 주기: {self.timeframe!r}")
        if key == self.timeframe:
            return self
        return ChartDisplayOptions(
            timeframe=key,
            show_volume=self.show_volume,
            show_rsi=self.show_rsi,
            show_macd=self.show_macd,
            show_stochastic=self.show_stochastic,
            show_institution=self.show_institution,
            show_foreign=self.show_foreign,
            show_individual=self.show_individual,
        )

    @property
    def investor_columns(self) -> tuple[str, ...]:
        return tuple(
            column
            for column, enabled in (
                ("institution", self.show_institution),
                ("foreign", self.show_foreign),
                ("individual", self.show_individual),
            )
            if enabled
        )


__all__ = ["ChartDisplayOptions", "LABEL_TO_TIMEFRAME"]
