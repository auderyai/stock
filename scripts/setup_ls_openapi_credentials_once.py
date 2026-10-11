from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFormLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.application.ls_openapi_credentials import LSOpenApiCredentialService


class CredentialController:
    def __init__(self, service: LSOpenApiCredentialService) -> None: self.service = service
    def save(self, key: str, secret: str) -> None: self.service.register(key, secret)


class Dialog(QDialog):
    def __init__(self) -> None:
        super().__init__(); self.setWindowTitle("LS OpenAPI 키 1회 등록"); self.setMinimumWidth(620)
        self.key, self.secret = QLineEdit(), QLineEdit(); self.secret.setEchoMode(QLineEdit.Password)
        form = QFormLayout(); form.addRow("LS_APP_KEY", self.key); form.addRow("LS_APP_SECRET", self.secret)
        self.save_button = QPushButton("연결 확인 후 저장"); self.save_button.clicked.connect(self.store)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("LS_APP_KEY와 LS_APP_SECRET을 C:\\stock\\.env에 등록합니다.\n입력값은 화면·로그에 출력하지 않습니다."))
        layout.addLayout(form); layout.addWidget(self.save_button)
        self.controller = CredentialController(LSOpenApiCredentialService(ROOT))

    def store(self) -> None:
        self.save_button.setEnabled(False); QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.controller.save(self.key.text(), self.secret.text())
        except Exception as exc:
            QMessageBox.critical(self, "등록 실패", f"LS OpenAPI 연결 확인에 실패했습니다.\n{type(exc).__name__}: {exc}")
        else:
            QMessageBox.information(self, "등록 완료", "토큰 발급을 확인하고 LS_APP_KEY/LS_APP_SECRET을 저장했습니다."); self.accept()
        finally:
            QApplication.restoreOverrideCursor(); self.save_button.setEnabled(True)


def main() -> int:
    app = QApplication(sys.argv); return Dialog().exec()


if __name__ == "__main__": raise SystemExit(main())
