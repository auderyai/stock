from __future__ import annotations

import numpy as np
import pandas as pd

from krx_research.analytics.indicator_scenario import INDICATORS
from krx_research.qt.presentation.table_policy import TablePresentationPolicy

EMA_CHANGE = {
    f"EMA {span} 일별 변화율 (%)": f"ema{span}_change_pct"
    for span in (5, 10, 15, 33, 56, 112, 224, 448)
}


class ScenarioPresenter:
    """Pure presentation/plot preparation shared by the PySide6 scenario view."""


    TABLE_POLICY = TablePresentationPolicy(
        right_columns=(
            "days", "baseline_price", "scenario_price", "required_price",
            "range", "validation",
        ),
        center_columns=("signal",),
    )

    CHECKPOINT_LABELS = {
        "days": "거래일",
        "baseline_price": "AI 기본 예상가",
        "scenario_price": "AI 지표변경 예상가",
        "required_price": "목표 도달 가상가격",
        "range": "AI 10~90% 범위",
        "validation": "검증 오차",
        "signal": "판정",
    }

    @staticmethod
    def checkpoint_frame(analysis) -> pd.DataFrame:
        rows = []
        for r in analysis.checkpoints:
            validation = (
                f"{r.validation_mae_pct:.2f}% (기준 {r.naive_mae_pct:.2f}%)"
                if np.isfinite(r.validation_mae_pct)
                else "시간순 검증 불가"
            )
            rows.append({
                "days": r.days,
                "baseline_price": f"{r.baseline_price:,.0f}",
                "scenario_price": f"{r.scenario_price:,.0f}",
                "required_price": f"{float(analysis.path.path.close.iloc[r.days - 1]):,.0f}",
                "range": f"{r.lower_price:,.0f} ~ {r.upper_price:,.0f}",
                "validation": validation,
                "signal": r.signal,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def training_text(analysis, daily_count: int) -> str:
        first = analysis.checkpoints[0]
        strength = " · 하락장 속 종목 상승: 상대강도 강함" if first.resisting_market_decline else ""
        context = first.market_context
        if analysis.market_index_name and ("80%" in context or "시장 지수 연동" in context):
            context = f"{analysis.market_index_name} 종합지수 DB · {context}"
        details = []
        for r in analysis.checkpoints:
            if np.isfinite(r.validation_direction_pct):
                details.append(
                    f"{r.days}일 예측: 모델 선택 {r.selection_start}~{r.selection_end}, "
                    f"학습 {r.train_start}~{r.train_end} ({r.train_count}건), "
                    f"검증 {r.test_start}~{r.test_end} ({r.test_count}건), "
                    f"방향 일치 {r.validation_direction_pct:.1f}%"
                )
            else:
                details.append(
                    f"{r.days}일 예측: 학습 {r.train_start}~{r.train_end} ({r.train_count}건), "
                    "시간순 검증 불가"
                )
        return (
            f"{context}{strength} · 시장 대비 1일 상대수익률 {first.relative_strength:+.2f}%p · "
            f"DB 일봉 {daily_count}거래일 · 지표 계산 후 학습 가능 {first.selected_count}거래일.  |  "
            + "  |  ".join(details)
        )

    @staticmethod
    def status_text(analysis, selected_indicator: str) -> str:
        path = analysis.path
        verdict = "목표 도달" if path.feasible else "선택한 기간에 목표 도달 불가 — 가장 가까운 경로 표시"
        if path.feasible and not path.within_historical_limits:
            verdict += " · 과거 1~99백분위 변동폭 초과(가상 시나리오)"
        current = float(analysis.current_features[INDICATORS[selected_indicator]])
        return (
            f"{verdict}: {selected_indicator} {current:.2f} → {path.achieved_value:.2f} "
            f"(입력 {path.requested_value:.2f}), 마지막 가상 종가 {path.required_terminal_price:,.0f}원. "
            f"과거 {len(path.path)}일 수익률 1~99백분위 "
            f"{path.observed_return_limits[0]:+.1f}% ~ {path.observed_return_limits[1]:+.1f}%."
        )

    @staticmethod
    def indicator_labels(label: str) -> tuple[str, ...]:
        if label == "전체":
            return tuple(INDICATORS)[:6]
        if label == "EMA 변화율 전체":
            return tuple(EMA_CHANGE)
        return (label,)

    @staticmethod
    def indicator_column(label: str) -> str:
        return {**INDICATORS, **EMA_CHANGE}[label]
