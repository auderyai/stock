from __future__ import annotations

from io import BytesIO
import unittest
from unittest.mock import MagicMock
from zipfile import ZipFile

from krx_research.financial_backfill.client import (
    OpenDartClient,
    OpenDartError,
    OpenDartTransientError,
)
from krx_research.financial_backfill.models import FinancialPeriod


def _corp_zip() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "CORPCODE.xml",
            "<result><list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>"
            "<corp_eng_name>Samsung</corp_eng_name><stock_code>005930</stock_code>"
            "<modify_date>20261017</modify_date></list>"
            "<list><corp_code>00000001</corp_code><corp_name>비상장</corp_name>"
            "<stock_code> </stock_code></list></result>",
        )
    return output.getvalue()


class OpenDartClientTests(unittest.TestCase):
    def test_key_is_never_accepted_when_shape_is_invalid(self) -> None:
        with self.assertRaisesRegex(OpenDartError, "40자리"):
            OpenDartClient("secret")

    def test_company_catalog_keeps_only_listed_companies(self) -> None:
        session = MagicMock()
        response = MagicMock(content=_corp_zip())
        response.raise_for_status.return_value = None
        session.get.return_value = response
        with OpenDartClient("x" * 40, session) as client:
            companies = client.listed_companies()
        self.assertEqual(("00126380", "005930"), (companies[0].corp_code, companies[0].ticker))

    def test_no_data_is_a_valid_company_level_result(self) -> None:
        session = MagicMock()
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"status": "013", "message": "조회된 데이터가 없습니다."}
        session.get.return_value = response
        with OpenDartClient("x" * 40, session) as client:
            rows = client.statements("00126380", 2025, FinancialPeriod.Q1, "CFS")
        self.assertEqual([], rows)

    def test_transient_api_status_is_retried_once(self) -> None:
        session = MagicMock()
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.side_effect = [
            {"status": "800", "message": "점검"},
            {"status": "800", "message": "점검"},
        ]
        session.get.return_value = response
        with OpenDartClient("x" * 40, session) as client:
            with self.assertRaises(OpenDartTransientError):
                client.statements("00126380", 2025, FinancialPeriod.Q1, "CFS")
        self.assertEqual(2, session.get.call_count)

    def test_company_catalog_surfaces_key_error_without_printing_key(self) -> None:
        session = MagicMock()
        response = MagicMock(
            content=b"<result><status>010</status><message>invalid</message></result>"
        )
        response.raise_for_status.return_value = None
        session.get.return_value = response
        with OpenDartClient("x" * 40, session) as client:
            with self.assertRaisesRegex(OpenDartError, "010") as raised:
                client.listed_companies()
        self.assertNotIn("x" * 40, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
