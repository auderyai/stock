from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib import font_manager, rcParams

from krx_research.analytics.indicator_scenario import INDICATORS
from krx_research.qt.presentation.scenario_presenter import EMA_CHANGE, ScenarioPresenter


class ScenarioPlotter:
    """Matplotlib presentation logic; QWidget classes only host the canvases."""

    def __init__(self):
        self._configure_korean_font()

    @staticmethod
    def _configure_korean_font() -> None:
        for path in (
            Path(r"C:\Windows\Fonts\malgun.ttf"),
            Path(r"C:\Windows\Fonts\NanumGothic.ttf"),
            Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        ):
            if path.is_file():
                font_manager.fontManager.addfont(str(path))
                rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
                break
        rcParams["axes.unicode_minus"] = False

    def draw_price(self, figure, analysis) -> None:
        figure.clear()
        axis = figure.add_subplot(111)
        rows, path = analysis.checkpoints, analysis.path
        x = [0, *[r.days for r in rows]]
        axis.plot(x, [rows[0].current_price, *[r.baseline_price for r in rows]], "o--", label="AI 기본 예상")
        axis.plot(x, [rows[0].current_price, *[r.scenario_price for r in rows]], "o--", label="AI 지표변경 예상")
        axis.plot(range(len(path.path) + 1), [rows[0].current_price, *path.path.close], linewidth=2.4, label="목표 일치 가상가격")
        axis.fill_between(
            [r.days for r in rows],
            [r.lower_price for r in rows],
            [r.upper_price for r in rows],
            alpha=.13,
            label="AI 오차 10~90%",
        )
        axis.set_ylabel("가격(원)")
        axis.set_xlabel("거래일")
        axis.grid(alpha=.2)
        axis.legend()
        figure.tight_layout()

    def draw_indicators(self, figure, analysis, selected_indicator: str, visible_label: str, display_days: int) -> str:
        figure.clear()
        labels = ScenarioPresenter.indicator_labels(visible_label)
        current = analysis.current_features
        path = analysis.path
        display_days = max(1, len(path.path) if path is not None else display_days)
        summary: list[str] = []
        for index, name in enumerate(labels, 1):
            column = ScenarioPresenter.indicator_column(name)
            axis = figure.add_subplot((len(labels) + 3) // 4, 4, index) if len(labels) > 1 else figure.add_subplot(111)
            today = float(current[column])
            if not np.isfinite(today):
                axis.set_title(name)
                axis.text(.5, .5, "과거 거래일 부족", transform=axis.transAxes, ha="center", va="center")
                summary.append(f"{name}: 과거 거래일 부족")
                continue
            if path is not None and column in path.path:
                future = path.path[column].astype(float).to_numpy()
                axis.plot(range(len(future) + 1), [today, *future], linewidth=1.8, label="시나리오")
                if name == selected_indicator:
                    axis.axhline(path.requested_value, linestyle="--", linewidth=1, label="목표")
                summary.append(f"{name}: {today:.2f} → {future[-1]:.2f}")
            else:
                summary.append(f"{name}: 현재 {today:.2f}")
            axis.scatter([0], [today], s=24, zorder=3, label="현재")
            axis.set_xlim(0, display_days)
            axis.set_title(name)
            axis.set_ylabel("%" if column.startswith("ema") or column == "macd_pct" else "")
            axis.set_xlabel("거래일")
            axis.grid(alpha=.2)
            if len(labels) == 1:
                axis.legend(loc="best", fontsize=9)
        figure.tight_layout(pad=2.2)
        return "  |  ".join(summary)
