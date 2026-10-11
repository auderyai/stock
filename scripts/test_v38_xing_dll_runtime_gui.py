from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QTextEdit, QVBoxLayout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing.bridge import XingBridgeClient


class Worker(QThread):
    done = Signal(str)

    def run(self):
        lines = []
        try:
            with XingBridgeClient(ROOT, delay=.08, timeout=30) as client:
                lines.append("[1/3] DLL worker/login: PASS")
                r1 = client.raw_tr("t8424", {"gubun1": "0"})
                lines.append(f"[2/3] t8424: PASS ({len(r1.get('rows', []))} rows)")
                r2 = client.raw_tr("t8436", {"gubun": "0"})
                lines.append(f"[3/3] t8436: PASS ({len(r2.get('rows', []))} rows)")
                lines.append("")
                lines.append("V38 DLL runtime: READY")
        except Exception as exc:
            lines.append(f"FAIL: {type(exc).__name__}: {exc}")
        self.done.emit("\n".join(lines))


class Dialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LS xingAPI V38 DLL runtime 검사")
        self.resize(780, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "64bit PySide6 -> 32bit worker -> XingAPI.dll -> 공통 TrSchema/PacketCodec 경로를 실제 조회로 검사합니다."
        ))
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        self.button = QPushButton("DLL runtime 실제 검사")
        self.button.clicked.connect(self.start)
        layout.addWidget(self.button)
        self.worker = None

    def start(self):
        self.button.setEnabled(False)
        self.text.setPlainText("검사 중...")
        self.worker = Worker()
        self.worker.done.connect(self.finish)
        self.worker.start()

    def finish(self, text):
        self.text.setPlainText(text)
        self.button.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    d = Dialog()
    d.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
