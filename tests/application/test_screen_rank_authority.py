import ast
from pathlib import Path
import re
import unittest

from krx_research_nextgen.models.screen_catalog import SCREENS
from krx_research_nextgen.models.screening import ScreeningKind


class ScreenRankAuthorityTests(unittest.TestCase):
    def test_catalog_titles_do_not_embed_rank_numbers(self):
        source = Path(
            r"C:\stock\src\krx_research\policies\workstation_options.py"
        ).read_text(encoding="utf-8")
        module = ast.parse(source)
        legacy = next(
            ast.literal_eval(node.value) for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "SCREEN_TITLES" for target in node.targets)
        )
        titles = [spec.title for spec in SCREENS] + list(legacy.values())
        self.assertFalse([title for title in titles if re.search(r"Top\s*\d+", title, re.I)])

    def test_nextgen_catalog_does_not_own_a_limit(self):
        self.assertTrue(all(not hasattr(spec, "limit") for spec in SCREENS))

    def test_item_20_is_ema20_leading_sector(self):
        self.assertGreaterEqual(len(SCREENS), 20)
        item = SCREENS[19]
        self.assertEqual(item.title, "20일선+주도섹터")
        self.assertEqual(item.kind, ScreeningKind.EMA20_LEADING_SECTOR)
        self.assertEqual(item.market, "KOSPI+KOSDAQ")

    def test_only_daily_bollinger_breadth_screens_ignore_rank_limit(self):
        unranked = {spec.kind for spec in SCREENS if not spec.uses_rank_limit}
        self.assertEqual(unranked, {
            ScreeningKind.DAILY_BOLLINGER_UPPER_BREAKOUT,
            ScreeningKind.DAILY_BOLLINGER_LOWER_BREAKOUT,
        })


if __name__ == "__main__":
    unittest.main()
