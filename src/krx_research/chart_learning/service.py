from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd

from krx_research.archive.paths import ArchiveLayout, safe_segment
from krx_research.collectors import normalize_ticker
from krx_research.policies.chart_analysis import (
    DEFAULT_CHART_ANALYSIS_POLICY, ChartAnalysisPolicy,
)
from .models import ChartPatternSample, StoredChartPattern
from .repository import ChartLearningRepository


class ChartPatternFeatureService:
    """Produces reproducible price/EMA/DB-volume facts without storing market data."""

    def __init__(self, policy: ChartAnalysisPolicy = DEFAULT_CHART_ANALYSIS_POLICY):
        self.policy = policy

    def extract(self, history: pd.DataFrame, start, end) -> tuple[dict, object]:
        data = history.sort_values("trade_date").copy()
        close = pd.to_numeric(data["close"], errors="raise")
        for period in self.policy.moving_average_periods:
            data[f"ema_{period}"] = close.ewm(
                span=period, adjust=False, min_periods=period
            ).mean()
        segment = data[data["trade_date"].dt.date.between(start, end)]
        if segment.empty:
            raise ValueError("지정한 학습 기간에 Stock DB 자료가 없습니다.")
        first, last = float(segment.iloc[0]["close"]), float(segment.iloc[-1]["close"])
        peak = float(segment["high"].max())
        volume = pd.to_numeric(segment["volume"], errors="raise")
        latest = segment.iloc[-1]
        ema = {str(period): self._number(latest[f"ema_{period}"])
               for period in self.policy.moving_average_periods}
        features = {
            "observations": int(len(segment)),
            "period_return_pct": round((last / first - 1.0) * 100.0, 4),
            "peak_from_start_pct": round((peak / first - 1.0) * 100.0, 4),
            "last_from_peak_pct": round((last / peak - 1.0) * 100.0, 4),
            "db_volume_total": int(volume.sum()),
            "db_volume_average": round(float(volume.mean()), 4),
            "db_volume_recent_20_average": round(float(volume.tail(20).mean()), 4),
            "latest_close": last,
            "latest_ema": ema,
            "volume_source": self.policy.volume_source,
        }
        return features, segment.iloc[-1]["trade_date"].date()

    def market_features(self, frame: pd.DataFrame) -> dict:
        names = {code: name for name, code in self.policy.market_context.indices}
        days = self.policy.market_context.volatility_days
        result = {}
        for code, group in frame.groupby("index_code"):
            close = pd.to_numeric(group.sort_values("trade_date")["close_price"], errors="raise")
            recent = close.pct_change(fill_method=None).dropna().tail(days)
            if len(recent) < days:
                raise ValueError(f"{names.get(str(code), code)} 최근 {days}거래일 지수 자료가 부족합니다.")
            result[names.get(str(code), str(code))] = {
                "return_pct": round(float((close.iloc[-1] / close.iloc[-days - 1] - 1) * 100), 4),
                "daily_volatility_pct": round(float(recent.std(ddof=0) * 100), 4),
                "observations": days,
            }
        return result

    @staticmethod
    def _number(value):
        return None if pd.isna(value) else round(float(value), 4)


class ChartLearningService:
    """Validates, archives and records one user-provided chart-learning sample."""

    _SUPPORTED = {".png", ".jpg", ".jpeg", ".webp"}

    def __init__(self, database_target, root: Path,
                 policy: ChartAnalysisPolicy = DEFAULT_CHART_ANALYSIS_POLICY):
        self.database_target, self.layout, self.policy = database_target, ArchiveLayout(root), policy
        self.features = ChartPatternFeatureService(policy)

    def store(self, sample: ChartPatternSample) -> StoredChartPattern:
        source = Path(sample.image).resolve()
        ticker = normalize_ticker(sample.ticker) if sample.ticker.strip() else ""
        if source.suffix.lower() not in self._SUPPORTED or not source.is_file():
            raise ValueError("학습 원본은 존재하는 PNG·JPG·WEBP 이미지여야 합니다.")
        if sample.start > sample.end:
            raise ValueError("차트 시작일은 마지막 봉 날짜보다 늦을 수 없습니다.")
        digest = self.layout.file_sha256(source)
        with ChartLearningRepository(self.database_target) as repository:
            repository.initialize()
            identity = repository.resolve(ticker, sample.company_name)
            ticker = identity["ticker"]
            features, db_date = self.features.extract(repository.history(ticker, sample.end),
                                                       sample.start, sample.end)
            index_codes = tuple(code for _name, code in self.policy.market_context.indices)
            features["market_context"] = self.features.market_features(
                repository.market_context(index_codes, sample.end)
            )
            target = self._archive_path(source, ticker, identity["company_name"], sample, digest)
            self._copy_once(source, target, digest)
            sample_id, duplicate = repository.save(
                digest=digest, ticker=ticker, company_name=identity["company_name"],
                start=sample.start, end=sample.end, db_reference_date=db_date,
                canonical_path=self.layout.relative_path(target), assessment=sample.assessment,
                rationale=sample.rationale, policy=self.policy.as_dict(), features=features,
            )
        return StoredChartPattern(
            sample_id, ticker, identity["company_name"], db_date, target, duplicate, features
        )

    def _archive_path(self, source: Path, ticker: str, name: str,
                      sample: ChartPatternSample, digest: str) -> Path:
        return (self.layout.storage_root / "01_기업분석" / f"{ticker}_{safe_segment(name)}"
                / "chart_learning" /
                f"{sample.start.isoformat()}_{sample.end.isoformat()}_{digest[:12]}{source.suffix.lower()}")

    def _copy_once(self, source: Path, target: Path, digest: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if self.layout.file_sha256(target) != digest:
                raise RuntimeError(f"같은 경로의 학습 원본 체크섬이 다릅니다: {target}")
            return
        temporary = target.with_suffix(target.suffix + ".tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
