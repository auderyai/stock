from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .pattern_similarity import PatternRepository, PatternSimilarity, TimeSeriesVectorizer


@dataclass(frozen=True, slots=True)
class PeriodPatternQuery:
    security: str
    start: date
    end: date
    top_n: int = 20

    def __post_init__(self) -> None:
        if not str(self.security).strip():
            raise ValueError("기준 종목을 입력하십시오.")
        if self.start >= self.end:
            raise ValueError("패턴 시작일은 종료일보다 빨라야 합니다.")
        if not 1 <= self.top_n <= 100:
            raise ValueError("검색 결과 수는 1~100이어야 합니다.")


@dataclass(frozen=True, slots=True)
class PeriodPattern:
    code: str
    name: str
    observations: int
    channels: dict[str, np.ndarray]
    return_pct: float
    range_pct: float


class PeriodPatternSearchService:
    """Compares the user-selected period without inferring a breakout event."""

    def __init__(self, repository: PatternRepository):
        self.repository = repository

    def search(self, query: PeriodPatternQuery) -> list[dict]:
        security = self.repository.resolve(query.security)
        history = self.repository.history(query.start, query.end)
        groups = {str(code): frame for code, frame in history.groupby("stock_code", sort=False)}
        reference = self._pattern(groups.get(security.code))
        if reference is None:
            raise ValueError(f"{security.name}의 지정 기간 패턴 관측치가 부족합니다.")
        matches = []
        for code, frame in groups.items():
            if code == security.code:
                continue
            candidate = self._pattern(frame)
            if candidate is None or candidate.observations < reference.observations * 0.8:
                continue
            scores = self._compare(reference, candidate)
            matches.append((scores["similarity"], code, candidate, scores))
        matches.sort(key=lambda item: (-item[0], item[1]))
        selected = matches[:query.top_n]
        codes = [reference.code, *(item[2].code for item in selected)]
        snapshots = self.repository.latest(codes)
        perfect = {"similarity": 100, "price_similarity": 100, "volume_similarity": 100}
        return [
            self._row(reference, snapshots.get(reference.code, {}), query, perfect, "기준 패턴"),
            *(self._row(item[2], snapshots.get(item[2].code, {}), query, item[3], "유사 패턴")
              for item in selected),
        ]

    @staticmethod
    def _pattern(frame: pd.DataFrame | None) -> PeriodPattern | None:
        if frame is None:
            return None
        data = frame.sort_values("trade_date").drop_duplicates("trade_date")
        data = data.dropna(subset=["close", "high", "low", "volume"])
        if len(data) < 12:
            return None
        vectorizer = TimeSeriesVectorizer()
        close = data.close.to_numpy(dtype=float)
        channels = {
            name: vectorizer.price(data[name].to_numpy(dtype=float))
            for name in ("close", "high", "low")
        }
        channels["volume"] = vectorizer.volume(data.volume.to_numpy(dtype=float))
        return PeriodPattern(
            str(data.stock_code.iloc[-1]), str(data.stock_name.iloc[-1]), len(data), channels,
            (close[-1] / close[0] - 1) * 100,
            (float(data.high.max()) / float(data.low.min()) - 1) * 100,
        )

    @staticmethod
    def _compare(reference: PeriodPattern, candidate: PeriodPattern) -> dict[str, float]:
        price = np.mean([
            PatternSimilarity._score(reference.channels[name], candidate.channels[name])
            for name in ("close", "high", "low")
        ])
        volume = PatternSimilarity._score(reference.channels["volume"], candidate.channels["volume"])
        return {"similarity": price * 0.85 + volume * 0.15,
                "price_similarity": price, "volume_similarity": volume}

    @staticmethod
    def _row(pattern: PeriodPattern, snapshot: dict, query: PeriodPatternQuery,
             scores: dict, role: str) -> dict:
        value = lambda key: snapshot.get(key)
        eok = lambda key: None if value(key) is None else round(float(value(key)) / 100_000_000, 2)
        return {
            "pattern_role": role, "stock_code": pattern.code,
            "stock_name": value("stock_name") or pattern.name,
            "similarity_pct": round(scores["similarity"], 2),
            "price_similarity_pct": round(scores["price_similarity"], 2),
            "volume_similarity_pct": round(scores["volume_similarity"], 2),
            "pattern_start": query.start, "pattern_end": query.end,
            "pattern_days": pattern.observations,
            "period_return_pct": round(pattern.return_pct, 2),
            "period_range_pct": round(pattern.range_pct, 2),
            "db_recent_date": value("trade_date"), "rise_pct": value("rise_pct"),
            "close": value("close"), "market_cap_eok": eok("market_cap"),
            "trading_value_eok": eok("trading_value"),
        }
