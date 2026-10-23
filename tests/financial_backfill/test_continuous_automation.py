from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ContinuousFinancialAutomationTests(unittest.TestCase):
    def test_cloud_checks_for_the_next_period_every_thirty_minutes(self) -> None:
        workflow = (ROOT / ".github/workflows/stock-opendart-financial.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('cron: "*/30 * * * *"', workflow)
        self.assertIn("group: stock-menu5-opendart-financial", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("if (( rc == 75 )); then", workflow)

    def test_local_sync_is_manual_and_retains_drive_archives(self) -> None:
        runner = (
            ROOT / "KRX_Menu_Launcher/sync_opendart_financial_from_drive.cmd"
        ).read_text(encoding="utf-8")
        self.assertIn("sync-ready-local", runner)
        self.assertNotIn("--cleanup-confirm", runner)
        self.assertNotIn('set "ROOT=C:\\stock"', runner)

    def test_periodic_local_sync_installers_are_disabled(self) -> None:
        for path in (
            "tools/setup/INSTALL_OPENDART_FINANCIAL_SYNC_ON_LOGON.cmd",
            "tools/setup/REGISTER_OPENDART_FINANCIAL_SYNC_TASK.cmd",
            "tools/setup/REGISTER_OPENDART_FINANCIAL_SYNC_TASK.ps1",
            "KRX_Menu_Launcher/RUN_OPENDART_FINANCIAL_SYNC_ON_LOGON.vbs",
        ):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("Register-ScheduledTask", text)
            self.assertNotIn("sync_opendart_financial_from_drive.cmd", text)


if __name__ == "__main__":
    unittest.main()
