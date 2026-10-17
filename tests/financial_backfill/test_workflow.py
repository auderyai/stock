from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class OpenDartWorkflowTests(unittest.TestCase):
    def test_workflow_uses_secret_and_menu5_name_without_exposing_value(self) -> None:
        text = (ROOT / ".github/workflows/stock-opendart-financial.yml").read_text("utf-8")
        self.assertIn("OPENDART_API_KEY: ${{ secrets.OPENDART_API_KEY }}", text)
        self.assertIn("menu5-opendart-financial:", text)
        self.assertIn("timeout-minutes: 355", text)
        self.assertNotIn("crtfc_key", text)


if __name__ == "__main__":
    unittest.main()
