"""Private local credential entry; database operations belong to the service."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from PySide6.QtCore import Signal

from PySide6.QtWidgets import QApplication, QDialog, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from krx_research.application.postgresql_setup import PostgreSQLSetupService
from krx_research.qt.workers.task_runner import TaskRunner


class PostgreSQLSetupController:
    def __init__(self, root: Path):
        self.root = root
        self.service = PostgreSQLSetupService(root)

    def save(self, admin, reader, reader_confirm, writer, writer_confirm):
        if reader != reader_confirm or writer != writer_confirm:
            raise ValueError("암호 확인 입력이 일치하지 않습니다.")
        self.service.configure(admin, reader, writer)
        python = Path(sys.executable).with_name("python.exe")
        result = subprocess.run(
            [str(python), str(self.root / "scripts" / "setup_postgresql.py")],
            cwd=self.root, capture_output=True, check=False,
        )
        if result.returncode:
            raise RuntimeError("계정 저장 후 연결 검증 실패")

    def migrate(self, admin, request, progress):
        return self.service.migrate18(admin, request, progress)


class PostgreSQLSetupDialog(QDialog):
    progress = Signal(str)

    def __init__(self, root: Path, migration: dict | None = None):
        super().__init__()
        self.migration = migration
        self.setWindowTitle("Stock PostgreSQL 18 복원·검증" if migration else "Stock PostgreSQL 16 계정 설정")
        self.setMinimumWidth(650)
        self.controller = PostgreSQLSetupController(root)
        self.runner = TaskRunner(self)
        self.busy = False
        self.fields = []
        form = QFormLayout()
        labels = ("PostgreSQL 18 postgres 관리자 암호",) if migration else (
            "postgres 관리자 암호", "새 krx_reader 암호", "읽기 암호 확인", "새 krx_writer 암호", "쓰기 암호 확인")
        for label in labels:
            field = QLineEdit()
            field.setEchoMode(QLineEdit.Password)
            self.fields.append(field)
            form.addRow(label, field)
        self.status = QLabel(
            "127.0.0.1:5432 / krx_research\n"
            "소유자 krx_owner(로그인 불가), 조회 krx_reader, 쓰기 krx_writer\n"
            "설치 시 정한 postgres 암호와 서로 다른 새 읽기·쓰기 암호를 직접 입력하십시오.\n"
            "빈 DB·권한·연결만 설정하며 백업 복원이나 자료 생성은 하지 않습니다."
        )
        self.status.setWordWrap(True)
        if migration:
            self.status.setText(
                "PostgreSQL 18 / 127.0.0.1:5433 / krx_research\n"
                "18 설치 시 정한 관리자 암호를 직접 입력하십시오. 기존 읽기·쓰기 암호는 안전하게 재사용합니다.\n"
                "백업 무결성·목록 검사 → 빈 DB 복원 → 전체 검증 통과 후 .env 전환.\n"
                "PostgreSQL 16과 5432의 DB는 보존합니다. 오류가 나면 자료를 삭제하지 않고 중단합니다."
            )
        self.progress.connect(self.status.setText)
        self.button = QPushButton("빈 DB·최소 권한 설정 및 연결 검증")
        if migration:
            self.button.setText("18 백업 검사·빈 DB 복원·검증")
        self.button.clicked.connect(self.save)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addLayout(form)
        layout.addWidget(self.button)

    def save(self):
        secrets = tuple(field.text() for field in self.fields)
        for field in self.fields:
            field.clear()
            field.setEnabled(False)
        self.busy = True
        self.button.setEnabled(False)
        self.status.setText("계정·권한 설정과 연결 검증 중입니다...")
        self.runner.submit(
            (lambda: self.controller.migrate(secrets[0], self.migration, self.progress.emit))
            if self.migration else (lambda: self.controller.save(*secrets)),
            on_result=lambda result: self.status.setText(
                "복원 및 전체 검증 완료. .env를 5433으로 전환했습니다.\n검증 보고서: " + result["report"]
                if self.migration else
                "설정 및 연결 검증 완료. .env에 읽기·쓰기 계정을 저장했습니다.\n"
                "백업은 복원하지 않았습니다. 창을 닫아도 됩니다."
            ),
            on_error=self.failed_setup,
            on_finished=self.finished_setup,
        )

    def failed_setup(self, trace: str):
        # The controller/service expose only fixed, sanitized errors, never driver diagnostics.
        message = trace.rstrip().splitlines()[-1]
        self.status.setText("설정 미완료. " + message + (
            "\n자료를 보존한 채 중단했습니다. 보고서를 확인하십시오." if self.migration else
            "\n비밀번호를 다시 입력하여 재시도할 수 있습니다."))

    def finished_setup(self):
        self.busy = False
        self.button.setEnabled(True)
        for field in self.fields:
            field.setEnabled(True)

    def closeEvent(self, event):
        event.ignore() if self.busy else event.accept()


def configure(root: Path, migration: dict | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = PostgreSQLSetupDialog(root, migration)
    dialog.show()
    return app.exec()
