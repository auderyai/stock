from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.application.openai_credentials import (  # noqa: E402
    OpenAICredentialRegistrationService,
)
from krx_research.qt.workers.task_runner import TaskRunner  # noqa: E402


class OpenAICredentialDialog(QDialog):
    """One-use credential entry view; never prints or retains the entered key."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenAI API 키 1회 등록")
        self.setMinimumWidth(620)
        self.service = OpenAICredentialRegistrationService(ROOT)
        self.runner = TaskRunner(self)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.model = QLineEdit("gpt-5.4")
        form = QFormLayout()
        form.addRow("OPENAI_API_KEY", self.key)
        form.addRow("OPENAI_MODEL", self.model)
        self.save_button = QPushButton("연결 확인 후 암호화 저장")
        self.save_button.clicked.connect(self._save)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "입력한 키를 OpenAI에서 확인한 뒤 현재 Windows 사용자 전용 DPAPI로 저장합니다.\n"
            "키는 .env·소스·로그·명령행에 기록하지 않습니다."
        ))
        layout.addLayout(form)
        layout.addWidget(self.save_button)

    def _save(self) -> None:
        key, model = self.key.text(), self.model.text()
        self.save_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.runner.submit(
            lambda saved_key=key, saved_model=model: self.service.register(
                saved_key, saved_model
            ),
            on_result=self._saved,
            on_error=self._failed,
            on_finished=self._finished,
        )
        self.key.clear()
        key = ""

    def _saved(self, path: Path) -> None:
        QMessageBox.information(
            self, "등록 완료",
            f"OpenAI API 키를 암호화하여 저장했습니다.\n{path}\n\nStock을 다시 실행하십시오.",
        )
        self.accept()

    def _failed(self, trace: str) -> None:
        tail = next((line for line in reversed(trace.splitlines()) if line.strip()), "등록 실패")
        message = tail.split(":", 1)[-1].strip()
        QMessageBox.critical(self, "등록 실패", message[:500])

    def _finished(self) -> None:
        QApplication.restoreOverrideCursor()
        self.save_button.setEnabled(True)


def main() -> int:
    app = QApplication(sys.argv)
    return OpenAICredentialDialog().exec()


if __name__ == "__main__":
    raise SystemExit(main())
