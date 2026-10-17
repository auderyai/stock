from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from krx_research.cloud_sync.archive import DeltaArchiveApplier


class FinancialArchiveKindTests(unittest.TestCase):
    def test_financial_archive_cannot_be_read_as_daily_delta(self) -> None:
        connection = MagicMock()
        applier = DeltaArchiveApplier(
            connection, tables=(), expected_kind="financial-delta"
        )
        with patch(
            "krx_research.cloud_sync.archive._extracted_archive"
        ) as extracted, patch(
            "krx_research.cloud_sync.archive._load_and_verify_manifest",
            side_effect=RuntimeError("wrong-kind"),
        ) as verify:
            extracted.return_value.__enter__.return_value = Path.cwd()
            with self.assertRaisesRegex(RuntimeError, "wrong-kind"):
                applier.apply(Path("unused.tar.gz"))
        self.assertEqual("financial-delta", verify.call_args.kwargs["expected_kind"])


if __name__ == "__main__":
    unittest.main()
