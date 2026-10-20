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

    def test_local_sync_repeats_without_overlapping(self) -> None:
        task = (
            ROOT / "tools/setup/REGISTER_OPENDART_FINANCIAL_SYNC_TASK.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("-Minutes 10", task)
        self.assertIn("-MultipleInstances IgnoreNew", task)
        self.assertIn("sync_opendart_financial_from_drive.cmd", task)
        self.assertIn("-RunLevel Limited", task)

        runner = (
            ROOT / "KRX_Menu_Launcher/sync_opendart_financial_from_drive.cmd"
        ).read_text(encoding="utf-8")
        self.assertIn('%~dp0..', runner)
        self.assertIn(
            "--cleanup-confirm DELETE_VERIFIED_FINANCIAL_ARCHIVES", runner
        )
        self.assertNotIn('set "ROOT=C:\\stock"', runner)

    def test_logon_installer_registers_the_repeating_task(self) -> None:
        installer = (
            ROOT / "tools/setup/INSTALL_OPENDART_FINANCIAL_SYNC_ON_LOGON.cmd"
        ).read_text(encoding="utf-8")

        self.assertIn("REGISTER_OPENDART_FINANCIAL_SYNC_TASK.cmd", installer)


if __name__ == "__main__":
    unittest.main()
