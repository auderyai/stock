from __future__ import annotations

from html import escape

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)


class AssistantPanel(QWidget):
    """Presentation-only assistant panel."""

    submitted = Signal(str)
    clearRequested = Signal()
    codeLibraryRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("Codex 구독 분석 대화 · DB 값 우선 · 1회용 코드는 메인과 격리")
        title.setStyleSheet("font-weight:700")
        layout.addWidget(title)
        self.conversation = QTextBrowser()
        self.conversation.setOpenExternalLinks(True)
        layout.addWidget(self.conversation, 1)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("DB·Stock 파일·차트·최신 자료에 관해 요청하십시오.")
        self.prompt.setMaximumHeight(80)
        layout.addWidget(self.prompt)
        actions = QHBoxLayout()
        self.code_button = QPushButton("1회용 코드 관리")
        actions.addWidget(self.code_button)
        actions.addStretch(1)
        self.clear_button = QPushButton("대화 지우기")
        self.send_button = QPushButton("전송")
        actions.addWidget(self.clear_button)
        actions.addWidget(self.send_button)
        layout.addLayout(actions)
        self.send_button.clicked.connect(self._submit)
        self.clear_button.clicked.connect(self.clearRequested.emit)
        self.code_button.clicked.connect(self.codeLibraryRequested.emit)

    def _submit(self) -> None:
        text = self.prompt.toPlainText().strip()
        if text:
            self.prompt.clear()
            self.append_message("사용자", text)
            self.submitted.emit(text)

    def append_message(self, role: str, text: str, citations=()) -> None:
        body = escape(str(text)).replace("\n", "<br>")
        sources = "".join(
            f'<br><a href="{escape(url)}">{escape(title)}</a>' for title, url in citations
        )
        self.conversation.append(f"<p><b>{escape(role)}</b><br>{body}{sources}</p>")

    def set_busy(self, busy: bool) -> None:
        self.send_button.setEnabled(not busy)
        self.prompt.setEnabled(not busy)

    def clear(self) -> None:
        self.conversation.clear()
