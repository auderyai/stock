from pathlib import Path
import os
import subprocess
import tempfile
import unittest


PATCH = Path(__file__).resolve().parents[2] / "INSTALL_STOCK_LAPTOP.cmd"


class LaptopInstallPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PATCH.read_text(encoding="utf-8")

    def test_preserves_secrets_and_existing_changes(self) -> None:
        self.assertIn("git pull --ff-only origin main", self.text)
        self.assertIn("Git pull was skipped", self.text)
        self.assertIn('if not exist "%ROOT%\\.env" copy "%ROOT%\\.env.example"', self.text)
        self.assertNotIn("copy /Y", self.text)
        self.assertNotIn("copy /Y C:\\stock\\.env", self.text)
        self.assertNotIn("OPENAI_API_KEY=", self.text)

    def test_registers_only_safe_delta_sync(self) -> None:
        self.assertIn("setup_postgresql.py", self.text)
        self.assertIn("--verify-stored", self.text)
        self.assertIn("REGISTER_PC_DRIVE_SYNC_TASK.cmd", self.text)
        self.assertIn("RUN_PC_DRIVE_SYNC.cmd", self.text)
        self.assertNotIn("INSTALL_OPENDART_FINANCIAL_SYNC_ON_LOGON.cmd", self.text)

    @unittest.skipUnless(os.name == "nt", "Requires Windows cmd.exe")
    def test_repository_detection_in_cmd(self) -> None:
        guards = [
            line.replace("goto existing_repo", "exit /b 10")
            .replace("goto occupied_root", "exit /b 20")
            for line in self.text.splitlines()
            if line.endswith(("goto existing_repo", "goto occupied_root"))
        ]
        self.assertEqual(len(guards), 2)
        with tempfile.TemporaryDirectory(prefix="stock install ") as directory:
            root = Path(directory) / "repository"
            probe = Path(directory) / "probe.cmd"
            probe.write_text(
                "@echo off\n" + f'set "ROOT={root}"\n'
                + "\n".join(guards) + "\nexit /b 30\n", encoding="utf-8"
            )
            for state, expected in (("missing", 30), ("occupied", 20), ("repository", 10)):
                with self.subTest(state=state):
                    if state == "occupied":
                        root.mkdir()
                    elif state == "repository":
                        (root / ".git").mkdir()
                    result = subprocess.run(
                        ["cmd.exe", "/d", "/c", str(probe)], capture_output=True, check=False
                    )
                    self.assertEqual(result.returncode, expected, result.stderr)

    @unittest.skipUnless(os.name == "nt", "Requires Windows cmd.exe")
    def test_configuration_creation_preserves_existing_file(self) -> None:
        guard = next(
            line for line in self.text.splitlines()
            if line.startswith('if not exist "%ROOT%\\.env" copy ')
        ).replace("goto failed", "exit /b 1")
        with tempfile.TemporaryDirectory(prefix="stock install ") as directory:
            root = Path(directory)
            template = root / ".env.example"
            configuration = root / ".env"
            probe = root / "probe.cmd"
            probe.write_text(
                '@echo off\n' + f'set "ROOT={root}"\n' + guard + '\nexit /b 0\n',
                encoding="utf-8",
            )
            for state, expected in (("missing_template", 1), ("new", 0), ("existing", 0)):
                with self.subTest(state=state):
                    if state == "new":
                        template.write_text("template\n", encoding="utf-8")
                    elif state == "existing":
                        configuration.write_text("preserve\n", encoding="utf-8")
                    result = subprocess.run(
                        ["cmd.exe", "/d", "/c", str(probe)], capture_output=True, check=False
                    )
                    self.assertEqual(result.returncode, expected, result.stderr)
                    if state != "missing_template":
                        self.assertEqual(
                            configuration.read_text(encoding="utf-8"),
                            "template\n" if state == "new" else "preserve\n",
                        )


if __name__ == "__main__":
    unittest.main()
