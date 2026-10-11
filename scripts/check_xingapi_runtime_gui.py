from __future__ import annotations

import platform
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing.runtime import XingRuntimeProbe


class XingRuntimeDialog(QDialog):
    GUIDE_URL = "https://openapi.ls-sec.co.kr/howto-sample"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LS xingAPI 실행환경 검사")
        self.setMinimumSize(680, 380)

        self.result = QTextEdit()
        self.result.setReadOnly(True)

        refresh = QPushButton("다시 검사")
        guide = QPushButton("LS xingAPI 공식 설치 안내")
        close = QPushButton("닫기")
        refresh.clicked.connect(self.refresh)
        guide.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.GUIDE_URL)))
        close.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(refresh)
        buttons.addWidget(guide)
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("xingAPI COM 등록 여부와 현재 Python 실행환경을 확인합니다."))
        layout.addWidget(self.result)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        status = XingRuntimeProbe.inspect()
        lines = [
            f"Python: {sys.version.split()[0]}",
            f"Python 아키텍처: {platform.architecture()[0]}",
            f"COM 객체: XA_Session.XASession",
            f"상태: {'사용 가능' if status.available else '사용 불가'}",
        ]
        if status.reason:
            lines.append(f"원인: {status.reason}")
        if status.hresult is not None:
            lines.append(f"HRESULT: {status.hresult}")
        if not status.available:
            lines.extend(
                [
                    "",
                    "현재 오류는 API 키 문제가 아니라 Windows COM 실행환경 문제입니다.",
                    "LS xingAPI 최신 버전을 설치/등록한 뒤 이 검사를 다시 실행하십시오.",
                    "설치 전에도 Stock 화면은 PostgreSQL DB 스냅샷을 우선 사용합니다.",
                ]
            )
        self.result.setPlainText("\n".join(lines))


def main() -> int:
    app = QApplication(sys.argv)
    return XingRuntimeDialog().exec()


if __name__ == "__main__":
    raise SystemExit(main())
