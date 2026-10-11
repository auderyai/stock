from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from krx_research.archive.paths import ArchiveLayout
from krx_research.research_archive.parsers import CodexImageParser, OpenAIImageParser, find_codex_executable


class ResearchArchiveTests(unittest.TestCase):
    def test_daily_image_source_path_is_hash_named_and_inside_stock(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "today.png"
            source.write_bytes(b"image")
            target = ArchiveLayout(directory).research_source_path(source, date(2026, 10, 8))
            self.assertEqual(target.parent.name, "SOURCES")
            self.assertTrue(target.name.endswith("_today.png"))
            self.assertTrue(target.is_relative_to(directory))

    def test_image_parser_preserves_source_values(self):
        class Response:
            ok = True
            @staticmethod
            def json():
                return {"output_text": '{"report_date":"2026-10-08","title":"오늘의 특징주",'
                        '"items":[{"category":"반도체","ticker":null,"stock_name":"삼성전기",'
                        '"return_pct":1.25,"trading_value_eok":10.5,"reason":"자료"}]}'}

        class Session:
            @staticmethod
            def post(*_args, **kwargs):
                self = kwargs["json"]
                assert self["store"] is False
                assert self["input"][0]["content"][1]["type"] == "input_image"
                return Response()

        with TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            image.write_bytes(b"not-a-real-image")
            parser = OpenAIImageParser.__new__(OpenAIImageParser)
            parser.key, parser.model, parser.session = "test", "test-model", Session()
            result = parser.parse(image)
        self.assertEqual(result.report_date, date(2026, 10, 8))
        self.assertEqual(result.observations[0].source_return_pct, 1.25)
        self.assertEqual(result.observations[0].source_trading_value_eok, 10.5)

    def test_user_date_allows_image_without_visible_date(self):
        class Response:
            ok = True
            @staticmethod
            def json():
                return {"output_text": '{"report_date":null,"title":"오늘의 특징주",'
                        '"items":[{"category":"반도체","ticker":null,"stock_name":"삼성전자",'
                        '"return_pct":null,"trading_value_eok":null,"reason":"자료"}]}' }

        class Session:
            @staticmethod
            def post(*_args, **_kwargs): return Response()

        with TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"; image.write_bytes(b"image")
            parser = OpenAIImageParser.__new__(OpenAIImageParser)
            parser.key, parser.model, parser.session = "test", "test-model", Session()
            result = parser.parse(image, report_date=date(2026, 10, 10))
        self.assertEqual(result.report_date, date(2026, 10, 10))
        self.assertEqual(result.metadata["report_date_source"], "USER_INPUT")

    def test_image_parser_explains_exhausted_api_credit(self):
        class Response:
            ok = False
            status_code = 429
            @staticmethod
            def json():
                return {"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted",
                                  "message": "You have no credits remaining."}}

        message = OpenAIImageParser._api_error(Response())
        self.assertIn("API 크레딧이 없습니다", message)
        self.assertIn("credit_balance_exhausted", message)

    def test_codex_parser_explains_usage_limit(self):
        message = CodexImageParser._failure("rate limit reached: usage limit")
        self.assertIn("Codex 사용 한도", message)

    def test_codex_locator_finds_desktop_install_without_path(self):
        from unittest.mock import patch
        with TemporaryDirectory() as directory:
            executable = Path(directory) / "OpenAI" / "Codex" / "bin" / "version" / "codex.exe"
            executable.parent.mkdir(parents=True); executable.write_bytes(b"")
            with patch.dict("os.environ", {"LOCALAPPDATA": directory, "PATH": ""}, clear=False):
                self.assertEqual(Path(find_codex_executable()), executable.resolve())


if __name__ == "__main__":
    unittest.main()
