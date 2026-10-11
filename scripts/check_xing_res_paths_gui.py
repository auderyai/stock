from __future__ import annotations
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QTextEdit, QVBoxLayout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing.query import XingResLocator


class Dialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stock xingAPI RES 검사")
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("C:\\stock 관리 RES 폴더 하나만 검사합니다."))
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        button = QPushButton("다시 검사")
        button.clicked.connect(self.refresh)
        layout.addWidget(button)
        self.refresh()

    def refresh(self):
        root = XingResLocator.managed_root().resolve()
        configured = XingResLocator._env_value("LS_XING_RES_DIR")
        lines = [
            f"관리 폴더: {root}",
            f"LS_XING_RES_DIR: {configured or '(미지정)'}",
            "",
        ]
        for tr in XingResLocator.REQUIRED_TRS:
            path = root / f"{tr}.res"
            lines.append(f"{tr}: {'FOUND' if path.is_file() else 'NOT FOUND'} -> {path}")
        lines.extend(("", f"필수 파일: {XingResLocator.score(root)}/{len(XingResLocator.REQUIRED_TRS)}"))
        self.text.setPlainText("\n".join(lines))


def main() -> int:
    app = QApplication(sys.argv)
    dialog = Dialog()
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
