from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class StockDriveWorkflowTests(unittest.TestCase):
    def test_scheduled_run_executes_all_checkpointed_stages(self) -> None:
        workflow = (ROOT / ".github/workflows/stock-daily-google-drive.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('cron: "37 20 * * 1-5"', workflow)
        self.assertIn('timezone: "Asia/Seoul"', workflow)
        self.assertIn('"${{ github.event_name }}" == "schedule"', workflow)
        self.assertIn("args+=(--stage all)", workflow)


if __name__ == "__main__":
    unittest.main()
