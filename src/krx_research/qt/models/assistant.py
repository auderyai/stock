from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True, slots=True)
class AssistantReply:
    """One assistant turn, optionally carrying a grid result."""

    text: str
    frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    labels: dict[str, str] = field(default_factory=dict)
    heading: str = "AI 분석 결과"
    citations: tuple[tuple[str, str], ...] = ()
    chart_ticker: str | None = None
