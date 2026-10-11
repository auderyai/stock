from __future__ import annotations

import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from krx_research_nextgen.workers.task_runner import TaskRunner


class _RegistrationDialog(QDialog):
    def __init__(self, code: str, parent=None):
        super().__init__(parent); self.setWindowTitle("검토 후 정식 코드 등록"); self.resize(900, 650)
        layout = QVBoxLayout(self); form = QFormLayout(); self.name = QLineEdit(); self.description = QLineEdit()
        form.addRow("등록 이름", self.name); form.addRow("용도·검증 내용", self.description); layout.addLayout(form)
        layout.addWidget(QLabel("등록 코드 · 계산 전용 보안검사를 다시 통과해야 합니다."))
        self.code = QPlainTextEdit(code); layout.addWidget(self.code, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)


class ReusableCodeWindow(QMainWindow):
    """Human approval boundary between one-off history and reusable code."""

    def __init__(self, assistant, parent=None):
        super().__init__(parent); self._assistant, self._tasks = assistant, TaskRunner(self)
        self.setWindowTitle("1회용 코드 이력·정식 재사용 관리"); self.resize(1180, 760); self._build(); self.refresh()

    def _build(self):
        page = QWidget(); layout = QVBoxLayout(page); self.setCentralWidget(page)
        layout.addWidget(QLabel("원본 실행 이력은 보존됩니다. 검토·수정 후 정식 등록한 코드만 재사용할 수 있습니다."))
        splitter = QSplitter(Qt.Orientation.Vertical); layout.addWidget(splitter, 1)
        history_page = QWidget(); history_layout = QVBoxLayout(history_page)
        row = QHBoxLayout(); row.addWidget(QLabel("1회용 실행 이력")); row.addStretch(1)
        register = QPushButton("선택 코드 검토·정식 등록"); register.clicked.connect(self._register); row.addWidget(register)
        history_layout.addLayout(row); self.history = self._table(("실행 시각", "실행 ID", "코드 해시", "동일 코드 실행", "검토 상태", "실행 상태", "출처")); history_layout.addWidget(self.history)
        library_page = QWidget(); library_layout = QVBoxLayout(library_page)
        row = QHBoxLayout(); row.addWidget(QLabel("정식 등록 코드")); row.addStretch(1)
        execute = QPushButton("선택 코드 재사용"); execute.clicked.connect(self._execute); row.addWidget(execute)
        refresh = QPushButton("새로고침"); refresh.clicked.connect(self.refresh); row.addWidget(refresh)
        library_layout.addLayout(row); self.library = self._table(("등록 이름", "버전", "버전 수", "사용 횟수", "마지막 사용", "설명")); library_layout.addWidget(self.library)
        splitter.addWidget(history_page); splitter.addWidget(library_page); splitter.setSizes([380, 300])
        self.status = QLabel(""); layout.addWidget(self.status)

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers)); table.setHorizontalHeaderLabels(headers); table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False); return table

    def refresh(self):
        runs, codes = self._assistant.one_off_runs(), self._assistant.reusable_codes()
        self._fill(self.history, runs, lambda row: (row.get("created_at"), row.get("run_id"),
                   str(row.get("code_hash") or "")[:12], row.get("repeat_count", 0),
                   "정식 등록 검토 권장" if row.get("promotion_recommended") else "", row.get("status"), row.get("origin")), "run_id")
        self._fill(self.library, codes, lambda row: (row.get("name"), row.get("active_version"), row.get("version_count"),
                   row.get("use_count"), row.get("last_used_at"), row.get("description")), "library_id")
        self.status.setText(f"실행 이력 {len(runs):,}건 · 정식 등록 코드 {len(codes):,}건")

    @staticmethod
    def _fill(table, rows, values, identity):
        table.setRowCount(len(rows))
        for r, record in enumerate(rows):
            for c, value in enumerate(values(record)):
                item = QTableWidgetItem("" if value is None else str(value)); item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if c < 5 else Qt.AlignmentFlag.AlignLeft)
                table.setItem(r, c, item)
            table.item(r, 0).setData(Qt.ItemDataRole.UserRole, record.get(identity))
        table.resizeColumnsToContents()

    @staticmethod
    def _selected(table):
        item = table.item(table.currentRow(), 0) if table.currentRow() >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _register(self):
        run_id = self._selected(self.history)
        if not run_id: QMessageBox.information(self, "정식 등록", "1회용 실행 이력을 선택하십시오."); return
        try: code = self._assistant.one_off_code(run_id)
        except Exception as error: QMessageBox.critical(self, "코드 읽기 오류", str(error)); return
        dialog = _RegistrationDialog(code, self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        try:
            row = self._assistant.register_reusable(run_id, dialog.name.text(), dialog.description.text(), dialog.code.toPlainText())
        except Exception as error: QMessageBox.critical(self, "등록 오류", str(error)); return
        self.refresh(); self.status.setText(f"정식 등록 완료: {row['name']} · 버전 {row['active_version']}")

    def _execute(self):
        library_id = self._selected(self.library)
        if not library_id: QMessageBox.information(self, "코드 재사용", "정식 등록 코드를 선택하십시오."); return
        text, accepted = QInputDialog.getMultiLineText(self, "등록 코드 재사용", "입력 JSON", "{}")
        if not accepted: return
        try: data = json.loads(text)
        except json.JSONDecodeError as error: QMessageBox.warning(self, "입력 오류", f"JSON 형식이 잘못되었습니다: {error}"); return
        self.status.setText("등록 코드를 새 격리 실행에서 수행 중입니다...")
        self._tasks.submit(lambda: self._assistant.run_reusable(library_id, data),
                           on_result=self._executed, on_error=lambda trace: QMessageBox.critical(self, "실행 오류", trace.splitlines()[-1]),
                           channel="reusable-code")

    def _executed(self, record):
        self.refresh(); self.status.setText(f"재사용 실행 완료 · 실행 ID {record.run_id}")
        QMessageBox.information(self, "실행 결과", json.dumps(record.result, ensure_ascii=False, indent=2, default=str)[:5000])
