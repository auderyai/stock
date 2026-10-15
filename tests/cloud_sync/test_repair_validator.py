from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "stock_drive_repair_validator", ROOT / "scripts" / "validate_stock_drive_repair.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class RepairValidatorTests(unittest.TestCase):
    def test_allows_only_stock_drive_runtime_and_tests(self) -> None:
        self.assertTrue(VALIDATOR._allowed("src/krx_research/cloud_sync/service.py"))
        self.assertTrue(VALIDATOR._allowed("scripts/stock_drive_sync.py"))
        self.assertFalse(VALIDATOR._allowed(".github/workflows/stock-drive-stage.yml"))
        self.assertFalse(VALIDATOR._allowed("nextgen/src/unrelated.py"))

    def test_detects_common_secret_formats(self) -> None:
        samples = (
            "sk-" + "a" * 24,
            "ghp_" + "b" * 24,
            "-----BEGIN PRIVATE KEY-----",
        )
        for sample in samples:
            self.assertTrue(any(pattern.search(sample) for pattern in VALIDATOR.SECRET_PATTERNS))


if __name__ == "__main__":
    unittest.main()
