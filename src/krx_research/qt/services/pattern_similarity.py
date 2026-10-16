from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from krx_research.database import open_research_store


class MovingAverageKind(StrEnum):
    SMA = "SMA"
    EMA = "EMA"
    WMA = "WMA"


@dataclass(frozen=True, slots=True)
class MovingAverageSpec:
    kind: MovingAverageKind = MovingAverageKind.SMA
    periods: tuple[int, ...] = (5, 20, 60)

    def __post_init__(self) -> None:
        periods = tuple(sorted(set(map(int, self.periods))))
        if not periods or len(periods) > 6 or periods[0] < 2 or periods[-1] > 250:
            raise ValueError("이동평균 기간은 2~250일에서 최대 6개까지 지정할 수 있습니다.")
        object.__setattr__(self, "kind", MovingAverageKind(str(self.kind).upper()))
        object.__setattr__(self, "periods", periods)


@dataclass(frozen=True, slots=True)
class PatternSearchQuery:
    security: str
    start: date
    end: date
    averages: MovingAverageSpec = MovingAverageSpec()
    top_n: int = 20
    include_price: bool = True
    include_volume: bool = False

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("패턴 시작일은 종료일보다 늦을 수 없습니다.")
        if not str(self.security).strip():
            raise ValueError("기준 종목을 입력하십시오.")
        if not 1 <= int(self.top_n) <= 100:
            raise ValueError("검색 결과 수는 1~100이어야 합니다.")
        if not self.include_price and not self.averages.periods:
            raise ValueError("비교할 가격 또는 이동평균선이 필요합니다.")


@dataclass(frozen=True, slots=True)
class Security:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class PatternVector:
    channels: dict[str, np.ndarray]
    observations: int


class PatternRepository(Protocol):
    def resolve(self, security: str) -> Security: ...
    def history(self, start: date, end: date) -> pd.DataFrame: ...
    def latest(self, codes: list[str]) -> dict[str, dict]: ...


class PatternVectorCache:
    """Disposable local cache; unchanged stock vectors are reused per search shape."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def load(self, query: PatternSearchQuery) -> dict[str, tuple[str, PatternVector | None]]:
        path = self._path(query)
        if not path.exists():
            return {}
        try:
            with np.load(path, allow_pickle=False) as saved:
                names = saved["channels"].tolist()
                codes, fingerprints = saved["codes"], saved["fingerprints"]
                observations, values = saved["observations"], saved["values"]
                return {
                    str(code): (str(fingerprint), None if not observations[index] else PatternVector(
                        {name: values[index, channel] for channel, name in enumerate(names)},
                        int(observations[index]),
                    ))
                    for index, (code, fingerprint) in enumerate(zip(codes, fingerprints))
                }
        except (OSError, ValueError, KeyError):
            return {}

    def save(self, query: PatternSearchQuery,
             vectors: dict[str, tuple[str, PatternVector | None]]) -> None:
        usable = [(code, fingerprint, vector) for code, (fingerprint, vector) in vectors.items()]
        if not usable:
            return
        sample = next((vector for _, _, vector in usable if vector), None)
        if sample is None:
            return
        names = tuple(sample.channels)
        empty = np.zeros((len(names), len(next(iter(sample.channels.values())))))
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(query)
        np.savez_compressed(
            path,
            codes=np.array([item[0] for item in usable]),
            fingerprints=np.array([item[1] for item in usable]),
            observations=np.array([item[2].observations if item[2] else 0 for item in usable]),
            channels=np.array(names),
            values=np.array([[item[2].channels[name] for name in names] if item[2] else empty
                             for item in usable]),
        )

    def _path(self, query: PatternSearchQuery) -> Path:
        payload = json.dumps({
            "start": query.start.isoformat(), "end": query.end.isoformat(),
            "kind": query.averages.kind.value, "periods": query.averages.periods,
            "price": query.include_price, "volume": query.include_volume,
        }, sort_keys=True).encode()
        return self.directory / f"{sha256(payload).hexdigest()[:20]}.npz"


class PostgreSQLPatternRepository:
    """Read-only OHLCV gateway for deterministic local pattern analysis."""

    def __init__(self, database_target):
        self.database_target = database_target

    def _rows(self, statement: str, params=()) -> list[dict]:
        with open_research_store(self.database_target, read_only=True) as store:
            return [dict(row) for row in store.conn.execute(statement, params).fetchall()]

    def resolve(self, security: str) -> Security:
        value = str(security).strip()
        rows = self._rows(
            "SELECT btrim(ticker) code,name FROM market.security_master "
            "WHERE btrim(ticker)=%s OR name=%s "
            "ORDER BY CASE WHEN btrim(ticker)=%s THEN 0 ELSE 1 END LIMIT 2",
            (value.zfill(6) if value.isdigit() else value, value, value.zfill(6)),
        )
        if not rows:
            raise ValueError(f"종목을 찾을 수 없습니다: {value}")
        if len(rows) > 1 and not value.isdigit():
            raise ValueError(f"같은 종목명이 여러 개입니다. 종목코드를 입력하십시오: {value}")
        return Security(str(rows[0]["code"]), str(rows[0]["name"] or value))

    def history(self, start: date, end: date) -> pd.DataFrame:
        rows = self._rows(
            "SELECT btrim(o.ticker) stock_code,COALESCE(m.name,btrim(o.ticker)) stock_name,"
            "o.trade_date::date trade_date,o.close::double precision close,"
            "o.volume::double precision volume "
            "FROM market.ohlcv_daily o LEFT JOIN market.security_master m "
            "ON btrim(m.ticker)=btrim(o.ticker) "
            "WHERE o.trade_date BETWEEN %s AND %s AND o.close>0 "
            "ORDER BY btrim(o.ticker),o.trade_date",
            (start.isoformat(), end.isoformat()),
        )
        frame = pd.DataFrame(rows)
        if frame.empty:
            raise ValueError("지정 기간의 주가 자료가 없습니다.")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        return frame

    def latest(self, codes: list[str]) -> dict[str, dict]:
        if not codes:
            return {}
        rows = self._rows(
            "WITH ranked AS ("
            " SELECT btrim(o.ticker) stock_code,o.trade_date::date trade_date,"
            " o.open::double precision open,o.high::double precision high,"
            " o.low::double precision low,o.close::double precision close,"
            " COALESCE(o.amount,o.close*o.volume)::double precision trading_value,"
            " row_number() OVER(PARTITION BY btrim(o.ticker) ORDER BY o.trade_date DESC) rn"
            " FROM market.ohlcv_daily o WHERE btrim(o.ticker)=ANY(%s)"
            ") SELECT cur.stock_code,m.name stock_name,cur.trade_date,cur.open,cur.high,cur.low,"
            "cur.close,cur.trading_value,m.market_cap::double precision market_cap,"
            "CASE WHEN prev.close>0 THEN (cur.close/prev.close-1)*100 END rise_pct "
            "FROM ranked cur LEFT JOIN ranked prev ON prev.stock_code=cur.stock_code AND prev.rn=2 "
            "LEFT JOIN market.security_master m ON btrim(m.ticker)=cur.stock_code WHERE cur.rn=1",
            (codes,),
        )
        return {str(row["stock_code"]): row for row in rows}


class PatternVectorizer:
    """Converts price, moving-average and volume paths into fixed-size vectors."""

    def __init__(self, spec: MovingAverageSpec, *, points: int = 64,
                 include_price: bool = True, include_volume: bool = False):
        self.spec, self.points = spec, int(points)
        self.include_price, self.include_volume = include_price, include_volume

    def vectorize(self, frame: pd.DataFrame, start: date, end: date) -> PatternVector | None:
        data = frame.sort_values("trade_date").drop_duplicates("trade_date").copy()
        data["close"] = pd.to_numeric(data["close"], errors="coerce")
        for period in self.spec.periods:
            data[f"ma_{period}"] = self._average(data["close"], period)
        mask = data.trade_date.between(pd.Timestamp(start), pd.Timestamp(end))
        view = data.loc[mask]
        columns = [f"ma_{period}" for period in self.spec.periods]
        if self.include_price:
            columns.insert(0, "close")
        if self.include_volume:
            columns.append("volume")
        view = view.dropna(subset=columns)
        if len(view) < 12:
            return None
        channels: dict[str, np.ndarray] = {}
        for column in columns:
            values = view[column].to_numpy(dtype=float)
            channels[column] = self._resample(
                self._standardize_volume(values) if column == "volume" else self._normalize(values)
            )
        return PatternVector(channels, len(view))

    def _average(self, series: pd.Series, period: int) -> pd.Series:
        if self.spec.kind == MovingAverageKind.EMA:
            return series.ewm(span=period, adjust=False, min_periods=period).mean()
        if self.spec.kind == MovingAverageKind.WMA:
            weights = np.arange(1, period + 1, dtype=float)
            return series.rolling(period).apply(lambda values: np.dot(values, weights) / weights.sum(), raw=True)
        return series.rolling(period).mean()

    @staticmethod
    def _normalize(values: np.ndarray) -> np.ndarray:
        base = values[0]
        if not np.isfinite(base) or base == 0:
            raise ValueError("패턴 기준값이 유효하지 않습니다.")
        return values / base - 1.0

    @staticmethod
    def _standardize_volume(values: np.ndarray) -> np.ndarray:
        values = np.log1p(np.maximum(values, 0))
        scale = values.std()
        return values - values.mean() if scale == 0 else (values - values.mean()) / scale

    def _resample(self, values: np.ndarray) -> np.ndarray:
        source = np.linspace(0.0, 1.0, len(values))
        return np.interp(np.linspace(0.0, 1.0, self.points), source, values)


class PatternSimilarity:
    """Scores channel shapes without hiding the component evidence."""

    @staticmethod
    def compare(reference: PatternVector, candidate: PatternVector) -> dict[str, float]:
        scores = {
            name: PatternSimilarity._score(reference.channels[name], candidate.channels[name])
            for name in reference.channels
        }
        price = scores.get("close")
        volume = scores.get("volume")
        averages = [score for name, score in scores.items() if name.startswith("ma_")]
        parts = [(price, 0.45), (sum(averages) / len(averages) if averages else None, 0.45),
                 (volume, 0.10)]
        active = [(value, weight) for value, weight in parts if value is not None]
        total = sum(weight for _, weight in active)
        return {
            "similarity": sum(value * weight for value, weight in active) / total,
            "price_similarity": price,
            "moving_average_similarity": sum(averages) / len(averages) if averages else None,
            "volume_similarity": volume,
        }

    @staticmethod
    def _score(left: np.ndarray, right: np.ndarray) -> float:
        rmse = float(np.sqrt(np.mean(np.square(left - right))))
        if left.std() == 0 or right.std() == 0:
            correlation_distance = 0.0 if np.allclose(left, right) else 1.0
        else:
            correlation_distance = (1.0 - float(np.corrcoef(left, right)[0, 1])) / 2.0
        return 100.0 * np.exp(-(3.5 * rmse + correlation_distance))


class PatternSimilaritySearchService:
    """Orchestrates one complete, local and reproducible cross-stock search."""

    def __init__(self, repository: PatternRepository, cache: PatternVectorCache | None = None):
        self.repository, self.cache = repository, cache

    def search(self, query: PatternSearchQuery) -> list[dict]:
        security = self.repository.resolve(query.security)
        warmup = query.start - timedelta(days=max(query.averages.periods) * 3)
        history = self.repository.history(warmup, query.end)
        vectorizer = PatternVectorizer(
            query.averages, include_price=query.include_price, include_volume=query.include_volume
        )
        groups = {str(code): group for code, group in history.groupby("stock_code", sort=False)}
        if security.code not in groups:
            raise ValueError(f"{security.name}({security.code})의 지정 기간 자료가 없습니다.")
        cached = self.cache.load(query) if self.cache else {}
        vectors: dict[str, tuple[str, PatternVector | None]] = {}
        changed = False
        for code, frame in groups.items():
            fingerprint = self._fingerprint(frame)
            match = cached.get(code)
            if match and match[0] == fingerprint:
                vector = match[1]
            else:
                vector = vectorizer.vectorize(frame, query.start, query.end)
                changed = True
            vectors[code] = (fingerprint, vector)
        if self.cache and (changed or set(cached) != set(vectors)):
            self.cache.save(query, vectors)
        reference = vectors[security.code][1]
        if reference is None:
            raise ValueError("기준 종목의 유효한 패턴 관측치가 부족합니다.")
        matches = []
        for code, frame in groups.items():
            if code == security.code:
                continue
            candidate = vectors[code][1]
            if candidate is None or candidate.observations < reference.observations * 0.8:
                continue
            scores = PatternSimilarity.compare(reference, candidate)
            matches.append((scores["similarity"], code, str(frame.stock_name.iloc[-1]), scores))
        matches.sort(reverse=True)
        selected = matches[: query.top_n]
        snapshots = self.repository.latest([code for _, code, _, _ in selected])
        return [self._row(code, name, scores, snapshots.get(code, {}), query)
                for _, code, name, scores in selected]

    @staticmethod
    def _fingerprint(frame: pd.DataFrame) -> str:
        last = frame.iloc[-1]
        return f"{len(frame)}:{last.trade_date}:{last.close}:{last.volume}"

    @staticmethod
    def _row(code: str, name: str, scores: dict, snapshot: dict,
             query: PatternSearchQuery) -> dict:
        value = lambda key: snapshot.get(key)
        return {
            "stock_code": code,
            "stock_name": value("stock_name") or name,
            "similarity_pct": round(scores["similarity"], 2),
            "price_similarity_pct": PatternSimilaritySearchService._round(scores["price_similarity"]),
            "moving_average_similarity_pct": PatternSimilaritySearchService._round(
                scores["moving_average_similarity"]
            ),
            "volume_similarity_pct": PatternSimilaritySearchService._round(scores["volume_similarity"]),
            "moving_average": f"{query.averages.kind.value} {','.join(map(str, query.averages.periods))}",
            "db_recent_date": value("trade_date"),
            "rise_pct": PatternSimilaritySearchService._round(value("rise_pct")),
            "close": value("close"), "open": value("open"),
            "high": value("high"), "low": value("low"),
            "market_cap_eok": PatternSimilaritySearchService._eok(value("market_cap")),
            "trading_value_eok": PatternSimilaritySearchService._eok(value("trading_value")),
        }

    @staticmethod
    def _round(value):
        return None if value is None else round(float(value), 2)

    @staticmethod
    def _eok(value):
        return None if value is None else round(float(value) / 100_000_000, 2)
