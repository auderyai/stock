from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class StockDriveWorkflowTests(unittest.TestCase):
    def test_scheduled_run_executes_all_checkpointed_stages(self) -> None:
        workflow = (ROOT / ".github/workflows/stock-daily-google-drive.yml").read_text(
            encoding="utf-8"
        )
        stage_workflow = (ROOT / ".github/workflows/stock-drive-stage.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('cron: "37 20 * * 1-5"', workflow)
        self.assertIn('timezone: "Asia/Seoul"', workflow)
        self.assertIn("scheduled-menu2:", workflow)
        self.assertIn("scheduled-menu5:", workflow)
        self.assertIn("needs: scheduled-menu2", workflow)
        self.assertIn("scheduled-menu7:", workflow)
        self.assertIn("needs: scheduled-menu5", workflow)
        self.assertIn("stage: menu2", workflow)
        self.assertIn("stage: menu5", workflow)
        self.assertIn("stage: menu7", workflow)
        self.assertIn("workflow_call:", stage_workflow)
        self.assertIn('args=(--stage "${{ inputs.stage }}")', stage_workflow)


if __name__ == "__main__":
    unittest.main()
