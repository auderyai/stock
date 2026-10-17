from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "opendart_financial_cli", ROOT / "scripts/opendart_financial_backfill.py"
)
assert SPEC and SPEC.loader
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


class FinancialBackfillCliTests(unittest.TestCase):
    def test_years_are_parsed_in_one_unambiguous_argument(self) -> None:
        args = CLI.parser().parse_args(
            ["--years", "2025,2024,2023", "cloud-menu5", "--max-batches", "1"]
        )
        self.assertEqual((2025, 2024, 2023), args.years)
        self.assertEqual(1, args.max_batches)


if __name__ == "__main__":
    unittest.main()
