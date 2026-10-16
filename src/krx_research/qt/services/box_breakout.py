from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .pattern_similarity import PatternRepository, PatternSimilarity


@dataclass(frozen=True, slots=True)
class BoxBreakoutQuery:
    security: str
    start: date
    end: date
    top_n: int = 20

    def __post_init__(self) -> None:
        if not str(self.security).strip():
            raise ValueError("기준 종목을 입력하십시오.")
        if self.start >= self.end:
            raise ValueError("박스권 시작일은 종료일보다 빨라야 합니다.")
        if not 1 <= self.top_n <= 100:
            raise ValueError("검색 결과 수는 1~100이어야 합니다.")


@dataclass(frozen=True, slots=True)
class BoxPattern:
    code: str
    name: str
    breakout_date: date
    box_high: float
    box_low: float
    width_pct: float
    breakout_pct: float
    volume_ratio: float
    timing_ratio: float
    path: np.ndarray


class BoxBreakoutSearchService:
    """Learns one selected box-breakout pattern and ranks analogous stocks."""

    def __init__(self, repository: PatternRepository):
        self.repository = repository

    def search(self, query: BoxBreakoutQuery) -> list[dict]:
        security = self.repository.resolve(query.security)
        history = self.repository.history(query.start, query.end)
        groups = {str(code): frame for code, frame in history.groupby("stock_code", sort=False)}
        reference = self._pattern(groups.get(security.code))
        if reference is None:
            raise ValueError(f"{security.name}의 지정 기간에서 박스권 상단 돌파를 찾지 못했습니다.")
        matches = []
        for code, frame in groups.items():
            if code == security.code:
                continue
            candidate = self._pattern(frame)
            if candidate:
                price, feature = self._compare(reference, candidate)
                matches.append((price * .7 + feature * .3, price, feature, candidate))
        matches.sort(key=lambda item: item[0], reverse=True)
        selected = matches[:query.top_n]
        codes = [reference.code, *(item[3].code for item in selected)]
        snapshots = self.repository.latest(codes)
        return [self._row(reference, snapshots.get(reference.code, {}), 100, 100, 100, "기준 패턴"),
                *(self._row(item[3], snapshots.get(item[3].code, {}), item[0], item[1], item[2], "유사 패턴")
                  for item in selected)]

    @staticmethod
    def _pattern(frame: pd.DataFrame | None) -> BoxPattern | None:
        if frame is None:
            return None
        data = frame.sort_values("trade_date").dropna(subset=["close", "high", "low", "volume"])
        if len(data) < 21:
            return None
        highs, closes = data.high.to_numpy(dtype=float), data.close.to_numpy(dtype=float)
        prior_highs = np.maximum.accumulate(highs)[:-1]
        events = np.flatnonzero(closes[20:] > prior_highs[19:]) + 20
        if not len(events):
            return None
        index = int(events[-1])
        box, row, high = data.iloc[:index], data.iloc[index], float(prior_highs[index - 1])
        low, average_volume = float(box.low.min()), float(box.volume.tail(20).mean())
        path = np.interp(np.linspace(0, 1, 64), np.linspace(0, 1, len(closes)), closes / closes[0] - 1)
        return BoxPattern(
            str(row.stock_code), str(row.stock_name), row.trade_date.date(), high, low,
            (high / low - 1) * 100, (float(row.close) / high - 1) * 100,
            float(row.volume) / average_volume if average_volume > 0 else 0,
            index / (len(data) - 1), path,
        )

    @staticmethod
    def _compare(reference: BoxPattern, candidate: BoxPattern) -> tuple[float, float]:
        price = PatternSimilarity._score(reference.path, candidate.path)
        left = np.array([reference.width_pct / 100, reference.breakout_pct / 30,
                         np.log1p(reference.volume_ratio) / 3, reference.timing_ratio])
        right = np.array([candidate.width_pct / 100, candidate.breakout_pct / 30,
                          np.log1p(candidate.volume_ratio) / 3, candidate.timing_ratio])
        return price, float(100 * np.exp(-2 * np.mean(np.abs(left - right))))

    @staticmethod
    def _row(pattern: BoxPattern, snapshot: dict, total: float, price: float,
             feature: float, role: str) -> dict:
        value = lambda key: snapshot.get(key)
        eok = lambda key: None if value(key) is None else round(float(value(key)) / 100_000_000, 2)
        return {
            "pattern_role": role, "stock_code": pattern.code,
            "stock_name": value("stock_name") or pattern.name,
            "similarity_pct": round(total, 2), "price_similarity_pct": round(price, 2),
            "box_similarity_pct": round(feature, 2), "breakout_date": pattern.breakout_date,
            "box_high": round(pattern.box_high, 2), "box_low": round(pattern.box_low, 2),
            "box_width_pct": round(pattern.width_pct, 2),
            "breakout_pct": round(pattern.breakout_pct, 2), "volume_ratio": round(pattern.volume_ratio, 2),
            "db_recent_date": value("trade_date"), "rise_pct": value("rise_pct"),
            "close": value("close"), "market_cap_eok": eok("market_cap"),
            "trading_value_eok": eok("trading_value"),
        }
