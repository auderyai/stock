from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from krx_research.daily_research_image import DailyResearchImageImporter
from krx_research.research_archive.models import ParsedResearchSource, SourceObservation
from krx_research.research_archive.parsers import _image_date


class _Layout:
    @staticmethod
    def file_sha256(_source): return "a" * 64


class _Archive:
    layout = _Layout()

    def initialize(self): pass
    def document_by_sha256(self, _digest): return None
    def store_parsed(self, _parsed): return {"document_id": "00000000-0000-0000-0000-000000000001"}
    def document_observations(self, _ids, _report_date=None):
        return [{
            "document_id": "00000000-0000-0000-0000-000000000001",
            "sha256": "a" * 64, "report_date": date(2026, 10, 11),
            "original_filename": "daily.png", "source_order": 1, "category": "반도체",
            "source_ticker": None, "ticker": "005930", "stock_name": "삼성전자",
            "reason": "원문 사유", "source_return_pct": 9.9,
            "source_trading_value_eok": 10.0, "db_trade_date": date(2026, 10, 11),
            "db_return_pct": 3.25, "db_trading_value_eok": 123.4,
            "market": "KOSPI", "authority": "DB_AUTHORITY", "raw_data": {},
        }]


class _Parser:
    def __init__(self, _root): pass
    def parse(self, path, *, report_date=None):
        return ParsedResearchSource(
            Path(path), "IMAGE", report_date or date(2026, 10, 11), "오늘의 특징주",
            observations=(SourceObservation("삼성전자"),),
        )


class DailyImageImportTests(unittest.TestCase):
    def importer(self, kind="featured"):
        importer = DailyResearchImageImporter.__new__(DailyResearchImageImporter)
        importer.kind, importer.root, importer.archive = kind, Path(r"C:\stock"), _Archive()
        return importer

    def test_missing_visible_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "기준일"):
            _image_date(None)

    def test_prepare_uses_db_values_as_final_values(self):
        with TemporaryDirectory() as directory:
            image = Path(directory) / "daily.png"; image.write_bytes(b"image")
            with patch("krx_research.daily_research_image.CodexImageParser", _Parser):
                plan = self.importer().prepare([str(image)], date(2026, 10, 10))
        row = plan.rows[0]
        self.assertEqual(row["report_date"], date(2026, 10, 10))
        self.assertEqual(row["source_return_pct"], 9.9)
        self.assertEqual(row["final_return_pct"], 3.25)
        self.assertEqual(row["final_trading_value_eok"], 123.4)

    def test_theme_requires_a_theme_name(self):
        archive = _Archive()
        original = archive.document_observations
        archive.document_observations = lambda ids, report_date=None: [{**original(ids, report_date)[0], "category": ""}]
        importer = self.importer("theme"); importer.archive = archive
        with TemporaryDirectory() as directory:
            image = Path(directory) / "daily.jpg"; image.write_bytes(b"image")
            with patch("krx_research.daily_research_image.CodexImageParser", _Parser), \
                 self.assertRaisesRegex(ValueError, "테마명"):
                importer.prepare([str(image)], date(2026, 10, 11))

    def test_featured_requires_source_reason(self):
        archive = _Archive(); original = archive.document_observations
        archive.document_observations = lambda ids, report_date=None: [{**original(ids, report_date)[0], "reason": ""}]
        importer = self.importer(); importer.archive = archive
        with TemporaryDirectory() as directory:
            image = Path(directory) / "daily.png"; image.write_bytes(b"image")
            with patch("krx_research.daily_research_image.CodexImageParser", _Parser), \
                 self.assertRaisesRegex(ValueError, "사유"):
                importer.prepare([str(image)], date(2026, 10, 11))


if __name__ == "__main__":
    unittest.main()
