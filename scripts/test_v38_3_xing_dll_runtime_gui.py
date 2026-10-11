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
                rows1 = r1.get("rows", [])
                lines.append(f"[2/3] t8424: PASS ({len(rows1)} rows)")
                if rows1:
                    lines.append(f"      first: {rows1[0]}")

                r2 = client.raw_tr("t8436", {"gubun": "0"})
                rows2 = r2.get("rows", [])
                lines.append(f"[3/3] t8436: PASS ({len(rows2)} rows)")
                if rows2:
                    lines.append(f"      first: {rows2[0]}")

                lines += ["", "V38.3 DLL runtime: READY"]
        except Exception as exc:
            lines.append(f"FAIL: {type(exc).__name__}: {exc}")
        self.done.emit("\\n".join(lines))


class Dialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LS xingAPI V38.3 DLL runtime 검사")
        self.resize(800, 560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "OCCURS fixed-width / CRLF framing을 공통 PacketCodec에서 자동 처리한 뒤 "
            "t8424/t8436을 실제 조회합니다."
        ))

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)

        self.button = QPushButton("V38.3 DLL runtime 실제 검사")
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
