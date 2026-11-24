from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace

from krx_research.infrastructure.xing_db.postgresql_repository import (
    PostgreSQLXingMenuRepository,
)


DAY = dt.date(2026, 11, 23)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _statement, _params):
        return _Result(self.rows)


class SectorResumeTests(unittest.TestCase):
    def test_only_valid_ohlc_rows_are_complete(self) -> None:
        rows = [
            {"sector_code": "001", "sector_name": "KOSPI", "open_price": 100, "high_price": 103,
             "low_price": 90, "close_price": 105},
            {"sector_code": "002", "sector_name": "대형주", "open_price": 100, "high_price": 110,
             "low_price": 90, "close_price": 105},
            {"sector_code": "003", "sector_name": "중형주", "open_price": 0, "high_price": 0,
             "low_price": 0, "close_price": 0},
            {"sector_code": "655", "sector_name": "파생지수", "open_price": 0, "high_price": 0,
             "low_price": 0, "close_price": 0},
        ]
        repository = PostgreSQLXingMenuRepository.__new__(PostgreSQLXingMenuRepository)
        repository._repo = SimpleNamespace(conn=_Connection(rows))

        self.assertEqual({"002", "655"}, repository.completed_sector_codes(DAY))


if __name__ == "__main__":
    unittest.main()
