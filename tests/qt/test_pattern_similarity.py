from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd

from krx_research.qt.services.assistant_service import AssistantService
from krx_research.qt.services.box_breakout import PeriodPatternQuery, PeriodPatternSearchService
from krx_research.qt.services.codex_subscription_backend import CodexSubscriptionBackend
from krx_research.qt.services.pattern_similarity import (
    MovingAverageKind, MovingAverageSpec, PatternSearchQuery, PatternSimilaritySearchService,
    PatternSimilarity, PatternVector, PatternVectorCache, PatternVectorizer, Security,
)
from krx_research.qt.services.pattern_policy import PatternQualityPolicy, UptrendPolicy


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
    def search_securities(self, query, limit=20):
        rows = [{"ticker": "078350", "name": "한양디지텍", "market": "KOSDAQ"}]
        return [row for row in rows if query in row["ticker"] or query in row["name"]][:limit]
    def history(self, start, end):
        return self.frame[self.frame.trade_date.between(pd.Timestamp(start), pd.Timestamp(end))]
    def latest_date(self): return self.frame.trade_date.max().date()
    def latest(self, codes):
        return {code: {"stock_name": "유사종목" if code == "000001" else "반대종목",
                       "trade_date": date(2026, 10, 15), "rise_pct": 1.25,
                       "close": 1000, "open": 980, "high": 1010, "low": 970,
                       "market_cap": 300_000_000_000, "trading_value": 12_000_000_000}
                for code in codes}


class PatternSimilarityTests(unittest.TestCase):
    def test_uptrend_policy_excludes_flat_and_falling_prices(self):
        dates = pd.bdate_range("2026-01-01", periods=30)
        frame = lambda close: FakeRepository._frame("000001", "검사", dates, close)
        policy = UptrendPolicy()
        self.assertTrue(policy.assess(frame(np.linspace(100, 130, 30))).accepted)
        self.assertFalse(policy.assess(frame(np.full(30, 100))).accepted)
        self.assertFalse(policy.assess(frame(np.linspace(130, 100, 30))).accepted)

    def test_quality_policy_excludes_discontinuity_and_long_term_bottom(self):
        dates = pd.bdate_range("2024-01-01", periods=300)
        frame = lambda close: FakeRepository._frame("000001", "검사", dates, close)
        policy = PatternQualityPolicy()
        self.assertTrue(policy.assess(frame(np.linspace(100, 160, 300))).accepted)
        discontinuous = np.r_[np.linspace(100, 120, 150), np.linspace(600, 650, 150)]
        self.assertFalse(policy.assess(frame(discontinuous)).accepted)
        bottom = np.r_[np.linspace(500, 100, 150), np.linspace(100, 120, 150)]
        self.assertFalse(policy.assess(frame(bottom)).accepted)

    def test_vectorizer_supports_user_selected_average(self):
        repository = FakeRepository()
        frame = repository.frame[repository.frame.stock_code == "078350"]
        vector = PatternVectorizer(MovingAverageSpec(MovingAverageKind.EMA, (5, 10, 15))).vectorize(
            frame, date(2026, 2, 2), date(2026, 5, 15)
        )
        self.assertEqual(set(vector.channels), {
            "close", "ma_5", "ma_10", "ma_15", "gap_close_5", "gap_close_10",
            "gap_close_15", "gap_5_10", "gap_5_15", "gap_10_15",
        })
        self.assertTrue(all(len(values) == 64 for values in vector.channels.values()))

    def test_eight_average_periods_are_supported_and_nine_are_rejected(self):
        periods = (5, 10, 15, 33, 56, 112, 224, 448)
        self.assertEqual(MovingAverageSpec(MovingAverageKind.EMA, periods).periods, periods)
        with self.assertRaisesRegex(ValueError, "최대 8개"):
            MovingAverageSpec(MovingAverageKind.EMA, (*periods, 500))

    def test_moving_average_gap_is_part_of_similarity(self):
        line = np.linspace(0, 0.1, 64)
        reference = PatternVector({"ma_5": line, "gap_5_20": np.zeros(64)}, 64)
        candidate = PatternVector({"ma_5": line, "gap_5_20": np.full(64, 0.1)}, 64)
        scores = PatternSimilarity.compare(reference, candidate)
        self.assertEqual(scores["moving_average_shape_similarity"], 100)
        self.assertLess(scores["moving_average_gap_similarity"], 100)
        self.assertLess(scores["moving_average_similarity"], 100)

    def test_search_ranks_matching_shape_and_adds_latest_facts(self):
        query = PatternSearchQuery(
            "078350", date(2026, 2, 2), date(2026, 5, 15),
            MovingAverageSpec(MovingAverageKind.SMA, (5, 10, 15)), top_n=2,
        )
        rows = PatternSimilaritySearchService(FakeRepository()).search(query)
        self.assertEqual(rows[0]["stock_code"], "000001")
        self.assertNotIn("000002", [row["stock_code"] for row in rows])
        self.assertEqual(rows[0]["moving_average"], "SMA 5,10,15")
        self.assertEqual(rows[0]["market_cap_eok"], 3000.0)
        self.assertEqual(rows[0]["trading_value_eok"], 120.0)
        self.assertEqual(rows[0]["pattern_end"], FakeRepository().latest_date())

    def test_search_excludes_stale_candidate_not_ending_on_latest_date(self):
        repository = FakeRepository()
        latest = repository.latest_date()
        repository.frame = repository.frame[
            ~((repository.frame.stock_code == "000001") &
              (repository.frame.trade_date == pd.Timestamp(latest)))
        ]
        query = PatternSearchQuery(
            "078350", date(2026, 2, 2), date(2026, 5, 15),
            MovingAverageSpec(MovingAverageKind.SMA, (5, 10, 15)), top_n=2,
        )
        rows = PatternSimilaritySearchService(repository).search(query)
        self.assertNotIn("000001", [row["stock_code"] for row in rows])

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

    def test_period_pattern_does_not_infer_a_breakout_event(self):
        repository = FakeRepository()
        reference_dates = pd.bdate_range("2026-04-01", periods=30)
        recent_dates = pd.bdate_range("2026-09-01", periods=30)
        reference_shape = np.linspace(130, 100, len(reference_dates)) + np.sin(
            np.linspace(0, 5, len(reference_dates))
        )
        recent_shape = np.linspace(100, 130, len(recent_dates)) + np.sin(
            np.linspace(0, 5, len(recent_dates))
        )
        target = repository._frame("078350", "기준종목", reference_dates, reference_shape)
        similar = repository._frame("000003", "유사종목", recent_dates, recent_shape)
        opposite = repository._frame("000004", "하락종목", recent_dates, recent_shape[::-1])
        repository.frame = pd.concat([target, similar, opposite], ignore_index=True)
        rows = PeriodPatternSearchService(repository).search(PeriodPatternQuery(
            "078350", reference_dates[0].date(), reference_dates[-1].date(), top_n=1,
        ))
        self.assertEqual([row["stock_code"] for row in rows], ["078350", "000003"])
        self.assertEqual(rows[0]["pattern_role"], "기준 패턴")
        self.assertLess(rows[0]["period_return_pct"], 0)
        self.assertEqual(rows[1]["pattern_role"], "최신 유사 패턴")
        self.assertGreater(rows[1]["period_return_pct"], 0)
        self.assertNotIn("breakout_date", rows[0])
        self.assertEqual(rows[0]["pattern_start"], reference_dates[0].date())
        self.assertEqual(rows[0]["pattern_end"], reference_dates[-1].date())
        self.assertEqual(rows[1]["pattern_start"], recent_dates[0].date())
        self.assertEqual(rows[1]["pattern_end"], recent_dates[-1].date())

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
