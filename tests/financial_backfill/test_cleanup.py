from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from krx_research.financial_backfill.cleanup import FinancialDriveCleanupService
from krx_research.financial_backfill.models import FinancialPeriod


def metadata(*, applied: bool = True, verified: int = 3) -> dict:
    return {
        "years": {
            "2025": {
                "local_completed": True,
                "local_verified_facts": verified,
                "periods": {
                    "Q1": {
                        "cloud_completed": True,
                        "facts": 3,
                        "batches": [{
                            "id": "file-1", "name": "batch.enc", "sha256": "hash",
                            "local_applied": applied,
                        }],
                    }
                },
            }
        }
    }


class FinancialDriveCleanupTests(unittest.TestCase):
    def test_deletes_only_fully_verified_local_archives(self) -> None:
        drive, save = MagicMock(), MagicMock()
        document = metadata()

        deleted = FinancialDriveCleanupService(drive, save).cleanup(
            document, 2025, (FinancialPeriod.Q1,)
        )

        self.assertEqual(["batch.enc"], deleted)
        drive.delete.assert_called_once_with("file-1")
        record = document["years"]["2025"]["periods"]["Q1"]["batches"][0]
        self.assertTrue(record["drive_deleted"])
        self.assertNotIn("id", record)
        self.assertNotIn("sha256", record)
        self.assertTrue(document["years"]["2025"]["drive_cleaned"])
        self.assertEqual(2, save.call_count)

    def test_rejects_unapplied_or_count_mismatched_archives(self) -> None:
        for document in (metadata(applied=False), metadata(verified=2)):
            drive = MagicMock()
            with self.assertRaisesRegex(RuntimeError, "완전 반영"):
                FinancialDriveCleanupService(drive, MagicMock()).cleanup(
                    document, 2025, (FinancialPeriod.Q1,)
                )
            drive.delete.assert_not_called()

    def test_checkpoint_preserves_progress_when_later_delete_fails(self) -> None:
        document = metadata()
        records = document["years"]["2025"]["periods"]["Q1"]["batches"]
        records.append({
            "id": "file-2", "name": "batch-2.enc", "sha256": "hash-2",
            "local_applied": True,
        })
        document["years"]["2025"].update(local_verified_facts=4)
        document["years"]["2025"]["periods"]["Q1"]["facts"] = 4
        drive, save = MagicMock(), MagicMock()
        drive.delete.side_effect = [None, RuntimeError("delete failed")]

        with self.assertRaisesRegex(RuntimeError, "delete failed"):
            FinancialDriveCleanupService(drive, save).cleanup(
                document, 2025, (FinancialPeriod.Q1,)
            )

        self.assertTrue(records[0]["drive_deleted"])
        self.assertFalse(records[1].get("drive_deleted", False))
        save.assert_called_once_with(document)


if __name__ == "__main__":
    unittest.main()
