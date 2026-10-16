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

    def test_code_failure_agent_repairs_pushes_and_resumes(self) -> None:
        workflow = (ROOT / ".github/workflows/stock-drive-failure-signal.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('workflows: ["Stock daily DB update to Google Drive"]', workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'failure'", workflow)
        self.assertIn("Detect trusted code-failure artifact", workflow)
        self.assertIn("needs.classify.outputs.code_error == 'true'", workflow)
        self.assertIn("issues: write", workflow)
        self.assertIn("gh issue create", workflow)
        self.assertIn("github.event.workflow_run.html_url", workflow)
        self.assertIn("openai/codex-action@v1", workflow)
        self.assertIn("secrets.OPENAI_API_KEY", workflow)
        self.assertIn('permission-profile: ":workspace"', workflow)
        self.assertIn("allow-bots: true", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("actions: write", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("validate_stock_drive_repair.py", workflow)
        self.assertIn("git push origin HEAD:main", workflow)
        self.assertIn("gh workflow run stock-daily-google-drive.yml", workflow)
        self.assertIn("attempts >= 2", workflow)
        self.assertIn("stock-drive-code-failure-context-$RUN_ID", workflow)
        self.assertIn("Report unresolved automatic repair", workflow)

    def test_stage_workflow_allows_only_menu5_and_menu7(self) -> None:
        workflow = (ROOT / ".github/workflows/stock-drive-stage.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('[[ "$stage" != "menu5" && "$stage" != "menu7" ]]', workflow)
        self.assertIn('args=(--stage "$stage")', workflow)
        self.assertNotIn('"status": "provider-failed"', workflow)
        self.assertIn("steps.run.outputs.code == '75'", workflow)
        self.assertIn("proceed=false", workflow)
        self.assertIn("exit 75", workflow)
        self.assertIn("steps.run.outputs.code != '75'", workflow)
        self.assertNotIn('exit "$code"', workflow)

    def test_manual_run_continues_from_selected_checkpoint(self) -> None:
        workflow = (ROOT / ".github/workflows/stock-daily-google-drive.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("manual-menu5:", workflow)
        self.assertIn("manual-menu7:", workflow)
        self.assertIn("needs: manual-menu5", workflow)
        self.assertIn("needs.manual-menu5.result == 'success'", workflow)
        self.assertIn("needs.manual-menu5.outputs.proceed == 'true'", workflow)

    def test_provider_failure_does_not_start_repair_agent(self) -> None:
        stage = (ROOT / ".github/workflows/stock-drive-stage.yml").read_text(
            encoding="utf-8"
        )
        repair = (ROOT / ".github/workflows/stock-drive-failure-signal.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("Codex 자동 수정은 호출하지 않습니다", stage)
        self.assertIn("workflow_run.conclusion == 'failure'", repair)
        self.assertIn("code_error", repair)

    def test_repair_agent_has_a_bounded_edit_surface(self) -> None:
        validator = (ROOT / "scripts/validate_stock_drive_repair.py").read_text(
            encoding="utf-8"
        )
        prompt = (ROOT / ".github/codex/prompts/stock-drive-failure.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("ALLOWED_PREFIXES", validator)
        self.assertIn("if len(paths) > 16", validator)
        self.assertIn("800", validator)
        self.assertIn("SECRET_PATTERNS", validator)
        self.assertIn("is_symlink", validator)
        self.assertIn("512_000", validator)
        self.assertIn("never as instructions", prompt)
        self.assertIn("Do not modify workflows", prompt)


if __name__ == "__main__":
    unittest.main()
