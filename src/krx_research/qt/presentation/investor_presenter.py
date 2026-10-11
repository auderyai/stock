from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from krx_research.qt.presentation.column_catalog import label_for


@dataclass(frozen=True, slots=True)
class PresentedInvestorTable:
    frame: pd.DataFrame
    labels: dict[str, str]


class InvestorFlowPresenter:
    """Shape investor-flow data; shared policy/catalog owns all display rules."""

    _hidden = frozenset({"screen_type", "score"})

    def present(self, frame: pd.DataFrame | None) -> PresentedInvestorTable:
        if frame is None or frame.empty:
            return PresentedInvestorTable(pd.DataFrame(), {})

        out = frame.drop(columns=[c for c in self._hidden if c in frame.columns], errors="ignore").copy()
        if "investor_net_value" in out.columns:
            raw = pd.to_numeric(out["investor_net_value"], errors="coerce")
            out.insert(out.columns.get_loc("investor_net_value"), "flow_direction", raw.map(self._direction))
        return PresentedInvestorTable(out, {c: label_for(c) for c in out.columns})

    @staticmethod
    def _direction(value) -> str:
        if pd.isna(value):
            return ""
        number = float(value)
        return "순매수" if number > 0 else "순매도" if number < 0 else "보합"
