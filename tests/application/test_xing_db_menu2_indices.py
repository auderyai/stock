from __future__ import annotations

import datetime as dt
import unittest

from krx_research.application.xing_db.e2e_models import Menu2Snapshot
from krx_research.application.xing_db.e2e_service import DbMenuE2EVerificationService
from krx_research.application.xing_db.service import MarketIndexPublisher, XingDbMenuService


DAY = dt.date(2026, 10, 16)


class _Bridge:
    def raw_tr(self, tr, values):
        if tr == "t8424":
            return {"rows": [
                {"upcode": "001", "hname": "코스피"},
                {"upcode": "301", "hname": "코스닥"},
                {"upcode": "201", "hname": "KOSPI200"},
                {"upcode": "305", "hname": "KOSDAQ150"},
            ]}
        if tr == "t8436":
            return {"rows": [{"shcode": "000001", "hname": "A"}]}
        if tr == "t1516":
            size = 200 if values["upcode"] == "201" else 150
            return {"rows": [
                {"shcode": f"{number:06d}", "hname": f"S{number}"}
                for number in range(size)
            ]}
        if tr == "t8429":
            return {"rows": [{"date": "20261016", "close": "100"}]}
        raise AssertionError(tr)


class _Repository:
    def __init__(self, published: int = 3) -> None:
        self.published = published
        self.publish_calls: list[dt.date] = []

    def latest_market_date(self): return DAY
    def upsert_sector_master(self, rows): return len(rows)
    def upsert_security_master(self, rows): return len(rows)
    def replace_index_membership(self, _as_of, _code, _name, rows): return len(rows)
    def completed_sector_codes(self, _as_of): return set()
    def upsert_sector_daily(self, _code, rows): return len(rows)

    def publish_market_indices(self, as_of):
        self.publish_calls.append(as_of)
        return self.published

    def market_index_source_dates(self, _start, _end):
        return [DAY]


class Menu2MarketIndexTests(unittest.TestCase):
    def test_publishes_market_indices_after_sector_collection(self) -> None:
        repository = _Repository()
        report = XingDbMenuService(_Bridge(), repository).run_menu2(as_of=DAY)

        self.assertTrue(report.passed)
        self.assertEqual([DAY], repository.publish_calls)
        self.assertEqual(3, report.stages[-1].affected_rows)

    def test_rejects_empty_market_index_publication(self) -> None:
        with self.assertRaisesRegex(ValueError, "0건"):
            XingDbMenuService(_Bridge(), _Repository(published=0)).run_menu2(as_of=DAY)

    def test_range_publishes_only_repository_verified_source_dates(self) -> None:
        repository = _Repository(published=59)

        published = MarketIndexPublisher(repository).publish_range(DAY, DAY)

        self.assertEqual(59, published)
        self.assertEqual([DAY], repository.publish_calls)

    def test_e2e_rejects_partial_market_index_publication(self) -> None:
        snapshot = Menu2Snapshot(
            DAY, 252, 3000, 200, 150, 252, 59, 58, 0, 0, 0, 0
        )

        problem = DbMenuE2EVerificationService._menu2_problem(0, snapshot)

        self.assertIn("canonical 발행 누락", problem)


if __name__ == "__main__":
    unittest.main()
