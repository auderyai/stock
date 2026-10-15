from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class StockDriveWorkflowTests(unittest.TestCase):
    def test_cloud_execution_surface_has_no_local_price_stage(self) -> None:
        paths = (
            ".github/workflows/stock-daily-google-drive.yml",
            ".github/workflows/stock-drive-stage.yml",
            "scripts/stock_drive_sync.py",
            "scripts/run_cloud_xing_stage.py",
            "src/krx_research/cloud_sync/service.py",
            "src/krx_research/cloud_sync/models.py",
            "requirements-cloud-worker.txt",
        )
        source = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in paths)
        forbidden = (
            "menu" + "2",
            "메뉴" + " 2",
            "market." + "ohlcv_daily",
            "py" + "krx",
            "finance-" + "datareader",
        )
        for token in forbidden:
            self.assertNotIn(token.lower(), source.lower())

    def test_scheduled_run_executes_only_cloud_stages(self) -> None:
        workflow = (ROOT / ".github/workflows/stock-daily-google-drive.yml").read_text(
            encoding="utf-8"
        )
        stage_workflow = (ROOT / ".github/workflows/stock-drive-stage.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('cron: "37 11 * * 1-5"', workflow)
        self.assertNotIn('timezone:', workflow)
        self.assertIn("scheduled-menu5:", workflow)
        self.assertIn("scheduled-menu7:", workflow)
        self.assertIn("needs: scheduled-menu5", workflow)
        self.assertIn("stage: menu5", workflow)
        self.assertIn("stage: menu7", workflow)
        self.assertIn("workflow_call:", stage_workflow)
        self.assertIn('args=(--stage "$stage")', stage_workflow)

    def test_failure_signal_creates_issue_only_for_failed_run(self) -> None:
        workflow = (ROOT / ".github/workflows/stock-drive-failure-signal.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('workflows: ["Stock daily DB update to Google Drive"]', workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'failure'", workflow)
        self.assertIn("issues: write", workflow)
        self.assertIn("gh issue create", workflow)
        self.assertIn("github.event.workflow_run.html_url", workflow)
        self.assertIn("openai/codex-action@v1", workflow)
        self.assertIn("secrets.OPENAI_API_KEY", workflow)

    def test_stage_workflow_allows_only_menu5_and_menu7(self) -> None:
        workflow = (ROOT / ".github/workflows/stock-drive-stage.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('[[ "$stage" != "menu5" && "$stage" != "menu7" ]]', workflow)
        self.assertIn('args=(--stage "$stage")', workflow)
        self.assertNotIn('"status": "provider-failed"', workflow)

    def test_manual_run_continues_from_selected_checkpoint(self) -> None:
        workflow = (ROOT / ".github/workflows/stock-daily-google-drive.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("manual-menu5:", workflow)
        self.assertIn("manual-menu7:", workflow)
        self.assertIn("needs: manual-menu5", workflow)
        self.assertIn("needs.manual-menu5.result == 'success'", workflow)


if __name__ == "__main__":
    unittest.main()
