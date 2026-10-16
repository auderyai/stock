from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd

from krx_research.qt.services.assistant_service import AssistantService
from krx_research.qt.services.box_breakout import BoxBreakoutQuery, BoxBreakoutSearchService
from krx_research.qt.services.codex_subscription_backend import CodexSubscriptionBackend
from krx_research.qt.services.pattern_similarity import (
    MovingAverageKind, MovingAverageSpec, PatternSearchQuery, PatternSimilaritySearchService,
    PatternVector, PatternVectorCache, PatternVectorizer, Security,
)


class FakeRepository:
    def __init__(self):
        dates = pd.bdate_range("2026-01-01", periods=120)
        shape = np.linspace(0, 18, len(dates)) + np.sin(np.linspace(0, 12, len(dates))) * 4
        self.frame = pd.concat([
            self._frame("078350", "한양디지텍", dates, 100 + shape),
            self._frame("000001", "유사종목", dates, 50 + shape / 2),
            self._frame("000002", "반대종목", dates, 120 - shape),
        ], ignore_index=True)

    @staticmethod
    def _frame(code, name, dates, close):
        return pd.DataFrame({"stock_code": code, "stock_name": name, "trade_date": dates,
                             "close": close, "high": np.asarray(close) * 1.01,
                             "low": np.asarray(close) * .99,
                             "volume": np.linspace(1000, 2000, len(dates))})

    def resolve(self, _security): return Security("078350", "한양디지텍")
    def history(self, start, end):
        return self.frame[self.frame.trade_date.between(pd.Timestamp(start), pd.Timestamp(end))]
    def latest(self, codes):
        return {code: {"stock_name": "유사종목" if code == "000001" else "반대종목",
                       "trade_date": date(2026, 10, 15), "rise_pct": 1.25,
                       "close": 1000, "open": 980, "high": 1010, "low": 970,
                       "market_cap": 300_000_000_000, "trading_value": 12_000_000_000}
                for code in codes}


class PatternSimilarityTests(unittest.TestCase):
    def test_vectorizer_supports_user_selected_average(self):
        repository = FakeRepository()
        frame = repository.frame[repository.frame.stock_code == "078350"]
        vector = PatternVectorizer(MovingAverageSpec(MovingAverageKind.EMA, (5, 10, 15))).vectorize(
            frame, date(2026, 2, 2), date(2026, 5, 15)
        )
        self.assertEqual(set(vector.channels), {"close", "ma_5", "ma_10", "ma_15"})
        self.assertTrue(all(len(values) == 64 for values in vector.channels.values()))

    def test_search_ranks_matching_shape_and_adds_latest_facts(self):
        query = PatternSearchQuery(
            "078350", date(2026, 2, 2), date(2026, 5, 15),
            MovingAverageSpec(MovingAverageKind.SMA, (5, 10, 15)), top_n=2,
        )
        rows = PatternSimilaritySearchService(FakeRepository()).search(query)
        self.assertEqual(rows[0]["stock_code"], "000001")
        self.assertGreater(rows[0]["similarity_pct"], rows[1]["similarity_pct"])
        self.assertEqual(rows[0]["moving_average"], "SMA 5,10,15")
        self.assertEqual(rows[0]["market_cap_eok"], 3000.0)
        self.assertEqual(rows[0]["trading_value_eok"], 120.0)

    def test_invalid_average_period_is_rejected(self):
        with self.assertRaises(ValueError):
            MovingAverageSpec(MovingAverageKind.EMA, (1, 5))

    def test_cache_preserves_vectors_and_insufficient_markers(self):
        query = PatternSearchQuery("078350", date(2026, 2, 2), date(2026, 5, 15))
        vector = PatternVector({"close": np.arange(64), "ma_5": np.arange(64)}, 70)
        with TemporaryDirectory() as directory:
            cache = PatternVectorCache(Path(directory))
            cache.save(query, {"000001": ("same", vector), "000002": ("short", None)})
            loaded = cache.load(query)
        self.assertEqual(loaded["000001"][1].observations, 70)
        self.assertIsNone(loaded["000002"][1])

    def test_box_breakout_requires_price_and_volume_confirmation(self):
        repository = FakeRepository()
        dates = pd.bdate_range("2026-09-01", periods=30)
        target = repository._frame("078350", "기준종목", dates, np.r_[np.full(29, 100), 105])
        target.loc[target.index[-1], "volume"] = 5000
        breakout = repository._frame("000003", "유사종목", dates, np.r_[np.full(29, 50), 52.5])
        breakout.loc[breakout.index[-1], "volume"] = 2500
        failed = repository._frame("000004", "미돌파", dates, np.full(30, 100))
        repository.frame = pd.concat([target, breakout, failed], ignore_index=True)
        rows = BoxBreakoutSearchService(repository).search(BoxBreakoutQuery(
            "078350", dates[0].date(), dates[-1].date(), top_n=10,
        ))
        self.assertEqual([row["stock_code"] for row in rows], ["078350", "000003"])
        self.assertEqual(rows[0]["pattern_role"], "기준 패턴")
        self.assertGreater(rows[0]["breakout_pct"], 1)

    def test_assistant_routes_pattern_search_to_registered_service(self):
        class Search:
            query = None
            def search(self, query):
                self.query = query
                return [{"stock_code": "000001", "similarity_pct": 95.0}]

        search = Search()
        with TemporaryDirectory() as directory:
            service = AssistantService(None, Path(directory), provider="codex",
                                       codex_backend=object(), pattern_service=search)
            output = service._call_tool("search_similar_patterns", """
                {"security":"078350","start_date":"2026-06-11","end_date":"2026-09-30",
                 "average_kind":"EMA","periods":[5,10,15],"top_n":20,
                 "include_price":true,"include_volume":false}
            """)
        self.assertEqual(search.query.averages.periods, (5, 10, 15))
        self.assertEqual(output["row_count"], 1)

    def test_codex_schema_exposes_pattern_action(self):
        self.assertIn("search_similar_patterns",
                      CodexSubscriptionBackend._SCHEMA["properties"]["action"]["enum"])


if __name__ == "__main__":
    unittest.main()
