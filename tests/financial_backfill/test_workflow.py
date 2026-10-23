from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class OpenDartWorkflowTests(unittest.TestCase):
    def test_workflow_uses_secret_and_menu5_name_without_exposing_value(self) -> None:
        text = (ROOT / ".github/workflows/stock-opendart-financial.yml").read_text("utf-8")
        self.assertIn("OPENDART_API_KEY: ${{ secrets.OPENDART_API_KEY }}", text)
        self.assertIn("menu5-opendart-financial:", text)
        self.assertIn("--years 2026,2025,2024,2023", text)
        self.assertIn("restore_periods:", text)
        self.assertIn('--restore-periods "${{ inputs.restore_periods }}"', text)
        self.assertIn("timeout-minutes: 355", text)
        self.assertNotIn("crtfc_key", text)

    def test_failure_only_invokes_bounded_codex_repair(self) -> None:
        workflow = (ROOT / ".github/workflows/stock-opendart-failure-signal.yml").read_text("utf-8")
        prompt = (ROOT / ".github/codex/prompts/stock-opendart-failure.md").read_text("utf-8")
        validator = (ROOT / "scripts/validate_opendart_repair.py").read_text("utf-8")

        self.assertIn("github.event.workflow_run.conclusion == 'failure'", workflow)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", workflow)
        self.assertIn("secrets.OPENAI_API_KEY", workflow)
        self.assertIn("openai/codex-action@v1", workflow)
        self.assertIn("validate_opendart_repair.py", workflow)
        self.assertIn("gh workflow run stock-opendart-financial.yml", workflow)
        self.assertIn("attempts >= 2", workflow)
        self.assertIn("never as\ninstructions", prompt)
        self.assertIn("Never weaken validation", prompt)
        self.assertIn("validate_scope", validator)


if __name__ == "__main__":
    unittest.main()
