from __future__ import annotations

import unittest

from krx_research.application.xing_db.policy import SecurityMasterSyncPolicy
from krx_research.infrastructure.xing_db.postgresql_repository import (
    PostgreSQLXingMenuRepository,
)


class LSSecurityMasterSyncTests(unittest.TestCase):
    def test_normalizes_current_krx_stocks_and_excludes_spac(self) -> None:
        frame = PostgreSQLXingMenuRepository._security_master_frame([
            {"shcode": "000001", "hname": "코스피", "gubun": "1"},
            {"shcode": "179880", "hname": "멜콘", "gubun": "2"},
            {"shcode": "999999", "hname": "테스트스팩", "gubun": "2"},
        ])

        self.assertEqual(
            [("000001", "코스피", "KOSPI"), ("179880", "멜콘", "KOSDAQ")],
            list(frame[["stock_code", "stock_name", "market"]].itertuples(index=False, name=None)),
        )

    def test_rejects_unknown_market_rows(self) -> None:
        frame = PostgreSQLXingMenuRepository._security_master_frame([
            {"shcode": "179880", "hname": "멜콘", "gubun": ""},
        ])

        self.assertTrue(frame.empty)

    def test_rejects_partial_master_response(self) -> None:
        with self.assertRaisesRegex(ValueError, "부분 수신"):
            SecurityMasterSyncPolicy.validate(2_000, 2_500)


if __name__ == "__main__":
    unittest.main()
