from __future__ import annotations

import datetime as dt
from dataclasses import replace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from krx_research.models.workstation import ScreenDataset
from krx_research.policies.screen_catalog import INVESTOR_FLOW_SCREEN_TYPES
from krx_research.policies.workstation_options import REALTIME_SOURCE_MODE


def filter_52w_distance(screen: ScreenDataset, lower_pct: float,
                        upper_pct: float) -> ScreenDataset:
    lower, upper = float(lower_pct), float(upper_pct)
    if not np.isfinite(lower) or not np.isfinite(upper) or lower > upper:
        raise ValueError("구간은 유한한 숫자로 입력하고, 시작값은 종료값 이하로 지정하세요.")
    if screen.screen_type != "near_high_52w":
        raise ValueError("52주 최고가 대비 종가 화면에서만 사용할 수 있습니다.")
    values = pd.to_numeric(screen.rows.get(
        "distance_from_52w_high_pct",
        pd.Series(index=screen.rows.index, dtype="float64"),
    ), errors="coerce").round(6)
    rows = screen.rows.loc[values.ge(lower) & values.le(upper)].copy()
    rows["rank"] = (rows.groupby("screen_date", sort=False).cumcount() + 1
                    if "screen_date" in rows else np.arange(1, len(rows) + 1))
    run = dict(screen.run)
    run.update(distance_lower_pct=lower, distance_upper_pct=upper)
    return replace(screen, rows=rows.reset_index(drop=True), run=run)


def describe_screen_freshness(dataset: ScreenDataset,
                              *, today: dt.date | None = None) -> str:
    current_date = today or dt.datetime.now(tz=ZoneInfo("Asia/Seoul")).date()
    screen_date = pd.Timestamp(dataset.run["as_of_date"]).date()
    price_date, indicator_date = dataset.latest_price_date, dataset.latest_indicator_date
    if dataset.screen_type in INVESTOR_FLOW_SCREEN_TYPES:
        return (f"확정 수급 {screen_date.isoformat()} · DB 일봉 마지막 "
                f"{price_date.isoformat() if price_date else '없음'}")
    if dataset.run.get("data_source_mode") == REALTIME_SOURCE_MODE:
        adjusted = int(dataset.run.get("adjusted_reference_count") or 0)
        suffix = f" · 자본변동 가격기준 보정 {adjusted:,}종목" if adjusted else ""
        return (f"실시간 가격 {screen_date.isoformat()} · 수집 "
                f"{dataset.run.get('retrieved_at') or '시각 미표시'} · 공급원 "
                f"{dataset.run.get('source') or '공급원 미표시'} · DB 지표 "
                f"{indicator_date.isoformat() if indicator_date else '없음'}{suffix}")
    dates = (f"스크린 {screen_date.isoformat()} · 지표 "
             f"{indicator_date.isoformat() if indicator_date else '없음'} · 가격 "
             f"{price_date.isoformat() if price_date else '없음'}")
    if price_date is None:
        return f"{dates} · 가격자료가 없습니다."
    if indicator_date is None or indicator_date < price_date:
        return f"{dates} · 기술지표 재계산이 필요합니다."
    if screen_date < indicator_date:
        return f"{dates} · 스크리닝 재실행이 필요합니다."
    if screen_date < current_date:
        return f"{dates} · 오늘 {current_date.isoformat()} 자료가 아직 없습니다(장 마감 전 또는 휴장일이면 정상)."
    return f"{dates} · 최신 상태입니다."
