from __future__ import annotations

import os
import shutil
from hashlib import sha256
from math import sqrt
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

    def market_features(self, frame: pd.DataFrame, stock: pd.DataFrame, start, end) -> dict:
        names = {code: name for name, code in self.policy.market_context.indices}
        policy = self.policy.market_context
        stock_returns = self._returns_until(
            stock, end, "close", policy.regime_lookback_days
        )
        result = {}
        for code, group in frame.groupby("index_code"):
            ordered = group.sort_values("trade_date").set_index("trade_date")
            close = pd.to_numeric(ordered["close_price"], errors="raise")
            returns = close.pct_change(fill_method=None).dropna()
            required = max(*policy.return_horizons, policy.regime_lookback_days)
            if len(returns) < required:
                raise ValueError(f"{names.get(str(code), code)} 시장 국면 자료가 {required}거래일보다 적습니다.")
            segment = close[close.index.date >= start]
            segment = segment[segment.index.date <= end]
            if len(segment) < 2:
                raise ValueError(f"{names.get(str(code), code)} 학습기간 지수 자료가 부족합니다.")
            market_returns = returns[returns.index.date <= end].tail(policy.regime_lookback_days)
            relationship = self._relationship(stock_returns, market_returns)
            sample_return = (segment.iloc[-1] / segment.iloc[0] - 1.0) * 100
            result[names.get(str(code), str(code))] = {
                "sample_return_pct": round(float(sample_return), 4),
                "recent_return_pct": {
                    str(days): round(float((close.iloc[-1] / close.iloc[-days - 1] - 1) * 100), 4)
                    for days in policy.return_horizons
                },
                "annualized_volatility_pct": {
                    str(days): round(float(returns.tail(days).std(ddof=0)
                                           * sqrt(policy.annualization_days) * 100), 4)
                    for days in policy.volatility_windows
                },
                "volatility_20d_percentile_252d": self._volatility_percentile(returns),
                "sample_max_drawdown_pct": round(float(
                    (segment / segment.cummax() - 1.0).min() * 100
                ), 4),
                "latest_vs_ema_pct": {
                    str(days): round(float((close.iloc[-1] / close.ewm(
                        span=days, adjust=False).mean().iloc[-1] - 1) * 100), 4)
                    for days in policy.volatility_windows
                },
                **relationship,
            }
        return result

    def _volatility_percentile(self, returns: pd.Series) -> float:
        policy = self.policy.market_context
        rolling = returns.rolling(policy.volatility_windows[0]).std(ddof=0).dropna()
        history = rolling.tail(policy.regime_lookback_days)
        return round(float(history.le(history.iloc[-1]).mean() * 100), 4)

    @staticmethod
    def _returns(frame: pd.DataFrame, start, end, column: str) -> pd.Series:
        ordered = frame.sort_values("trade_date").set_index("trade_date")
        returns = pd.to_numeric(ordered[column], errors="raise").pct_change(fill_method=None)
        return returns[(returns.index.date >= start) & (returns.index.date <= end)].dropna()

    @staticmethod
    def _returns_until(frame: pd.DataFrame, end, column: str, limit: int) -> pd.Series:
        ordered = frame.sort_values("trade_date").set_index("trade_date")
        returns = pd.to_numeric(ordered[column], errors="raise").pct_change(fill_method=None)
        return returns[returns.index.date <= end].dropna().tail(limit)

    @staticmethod
    def _relationship(stock: pd.Series, market: pd.Series) -> dict:
        aligned = pd.concat([stock.rename("stock"), market.rename("market")], axis=1).dropna()
        if len(aligned) < 20:
            raise ValueError("종목과 시장의 통계 관계를 계산할 공통 거래일이 부족합니다.")
        variance = aligned["market"].var(ddof=0)
        beta = 0.0 if variance == 0 else aligned.cov(ddof=0).loc["stock", "market"] / variance
        stock_return = (aligned["stock"] + 1.0).prod() - 1.0
        market_return = (aligned["market"] + 1.0).prod() - 1.0
        return {
            "stock_beta": round(float(beta), 4),
            "stock_market_correlation": round(float(aligned.corr().loc["stock", "market"]), 4),
            "stock_excess_return_pct": round(float((stock_return - market_return) * 100), 4),
            "beta_adjusted_residual_return_pct": round(float(
                (aligned["stock"] - beta * aligned["market"]).sum() * 100
            ), 4),
            "aligned_observations": int(len(aligned)),
        }

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
        source = Path(sample.image).resolve() if sample.image else None
        ticker = normalize_ticker(sample.ticker) if sample.ticker.strip() else ""
        if source and (source.suffix.lower() not in self._SUPPORTED or not source.is_file()):
            raise ValueError("학습 원본은 존재하는 PNG·JPG·WEBP 이미지여야 합니다.")
        if sample.start > sample.end:
            raise ValueError("차트 시작일은 마지막 봉 날짜보다 늦을 수 없습니다.")
        with ChartLearningRepository(self.database_target) as repository:
            repository.initialize()
            identity = repository.resolve(ticker, sample.company_name)
            ticker = identity["ticker"]
            history = repository.history(ticker, sample.end)
            features, db_date = self.features.extract(history, sample.start, sample.end)
            index_codes = tuple(code for _name, code in self.policy.market_context.indices)
            features["market_context"] = self.features.market_features(
                repository.market_context(index_codes, sample.end,
                                          self.policy.market_context.history_limit),
                history, sample.start, sample.end,
            )
            features["source_kind"] = "image_and_database" if source else "database"
            digest = (self.layout.file_sha256(source) if source else
                      self._database_digest(ticker, sample.start, sample.end))
            target = (self._archive_path(source, ticker, identity["company_name"], sample, digest)
                      if source else
                      f"postgresql:market.ohlcv_daily/{ticker}/{sample.start}/{sample.end}")
            if source:
                self._copy_once(source, target, digest)
            sample_id, duplicate = repository.save(
                digest=digest, ticker=ticker, company_name=identity["company_name"],
                start=sample.start, end=sample.end, db_reference_date=db_date,
                canonical_path=(self.layout.relative_path(target) if source else target),
                assessment=sample.assessment,
                rationale=sample.rationale, policy=self.policy.as_dict(), features=features,
            )
        return StoredChartPattern(
            sample_id, ticker, identity["company_name"], db_date, str(target), duplicate, features
        )

    @staticmethod
    def _database_digest(ticker: str, start, end) -> str:
        return sha256(f"database:{ticker}:{start}:{end}".encode()).hexdigest()

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
