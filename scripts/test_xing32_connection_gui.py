from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget

ROOT = Path(__file__).resolve().parents[1]


class Window(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LS xingAPI 32bit 연결/TR 검사")
        self.resize(820, 560)
        host = QWidget(); self.setCentralWidget(host); layout = QVBoxLayout(host)
        layout.addWidget(QLabel("64bit PySide6 → 32bit Worker → LS 로그인 → t8424/t8436을 실제 검사합니다."))
        self.output = QTextEdit(); self.output.setReadOnly(True); layout.addWidget(self.output, 1)
        self.button = QPushButton("검사 시작"); self.button.clicked.connect(self.start); layout.addWidget(self.button)
        self.process = QProcess(self); self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)

    def start(self) -> None:
        self.output.clear(); self.button.setEnabled(False)
        env = QProcessEnvironment.systemEnvironment(); env.insert("PYTHONPATH", str(ROOT / "src")); env.insert("PYTHONUTF8", "1")
        self.process.setProcessEnvironment(env); self.process.setWorkingDirectory(str(ROOT))
        self.process.start(str(ROOT / ".venv" / "Scripts" / "python.exe"), [str(ROOT / "scripts" / "test_xing32_connection.py")])

    def read_output(self) -> None:
        self.output.insertPlainText(bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace"))

    def finished(self, code: int, _status) -> None:
        self.read_output(); self.output.append("\n정상 완료" if code == 0 else f"\n실패 · 종료코드 {code}"); self.button.setEnabled(True)


def main() -> int:
    app = QApplication(sys.argv); window = Window(); window.show(); return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
