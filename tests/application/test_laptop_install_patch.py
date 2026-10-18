from pathlib import Path
import unittest


PATCH = Path(__file__).resolve().parents[2] / "INSTALL_STOCK_LAPTOP.cmd"


class LaptopInstallPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PATCH.read_text(encoding="utf-8")

    def test_preserves_secrets_and_existing_changes(self) -> None:
        self.assertIn("git pull --ff-only origin main", self.text)
        self.assertIn("Git pull was skipped", self.text)
        self.assertIn('if not exist "%ROOT%\\.env" copy', self.text)
        self.assertNotIn("copy /Y C:\\stock\\.env", self.text)
        self.assertNotIn("OPENAI_API_KEY=", self.text)

    def test_registers_only_safe_delta_sync(self) -> None:
        self.assertIn("setup_postgresql.py", self.text)
        self.assertIn("--verify-stored", self.text)
        self.assertIn("REGISTER_PC_DRIVE_SYNC_TASK.cmd", self.text)
        self.assertIn("RUN_PC_DRIVE_SYNC.cmd", self.text)
        self.assertNotIn("INSTALL_OPENDART_FINANCIAL_SYNC_ON_LOGON.cmd", self.text)


if __name__ == "__main__":
    unittest.main()
