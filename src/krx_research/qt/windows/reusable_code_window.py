from __future__ import annotations

import json
import pandas as pd

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from krx_research.qt.workers.task_runner import TaskRunner
from krx_research.qt.widgets.result_table import ResultTable


class _RegistrationDialog(QDialog):
    def __init__(self, code, parent=None):
        super().__init__(parent); self.setWindowTitle("검토 후 정식 코드 등록"); self.resize(900, 650)
        layout = QVBoxLayout(self); form = QFormLayout(); self.name, self.description = QLineEdit(), QLineEdit()
        form.addRow("등록 이름", self.name); form.addRow("용도·검증 내용", self.description); layout.addLayout(form)
        layout.addWidget(QLabel("등록 코드 · 계산 전용 보안검사를 다시 통과해야 합니다."))
        self.code = QPlainTextEdit(code); layout.addWidget(self.code, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)


class ReusableCodeWindow(QMainWindow):
    def __init__(self, assistant, parent=None):
        super().__init__(parent); self._assistant, self._runner = assistant, TaskRunner(self)
        self.setWindowTitle("1회용 코드 이력·정식 재사용 관리"); self.resize(1180, 760); self._build(); self.refresh()

    def _build(self):
        page = QWidget(); layout = QVBoxLayout(page); self.setCentralWidget(page)
        layout.addWidget(QLabel("원본 실행 이력은 보존됩니다. 검토·수정 후 정식 등록한 코드만 재사용할 수 있습니다."))
        split = QSplitter(Qt.Vertical); layout.addWidget(split, 1)
        first, first_layout = QWidget(), QVBoxLayout(); first.setLayout(first_layout)
        row = QHBoxLayout(); row.addWidget(QLabel("1회용 실행 이력")); row.addStretch(1); button = QPushButton("선택 코드 검토·정식 등록"); button.clicked.connect(self._register); row.addWidget(button); first_layout.addLayout(row)
        self.history = ResultTable(identity_width=0); first_layout.addWidget(self.history); split.addWidget(first)
        second, second_layout = QWidget(), QVBoxLayout(); second.setLayout(second_layout)
        row = QHBoxLayout(); row.addWidget(QLabel("정식 등록 코드")); row.addStretch(1); button = QPushButton("선택 코드 재사용"); button.clicked.connect(self._execute); row.addWidget(button); refresh = QPushButton("새로고침"); refresh.clicked.connect(self.refresh); row.addWidget(refresh); second_layout.addLayout(row)
        self.library = ResultTable(identity_width=0); second_layout.addWidget(self.library); split.addWidget(second)
        self.status = QLabel(); layout.addWidget(self.status); split.setSizes([380, 300])

    @staticmethod
    def _fill(table, rows, columns, labels, identity):
        frame = pd.DataFrame(({key: value(row) for key, value in columns.items()} for row in rows))
        frame[identity] = [row.get(identity) for row in rows]
        table.set_frame(frame, header_labels=labels)
        table.setColumnHidden(frame.columns.get_loc(identity), True)

    @staticmethod
    def _selected(table, identity):
        index = table.currentIndex()
        return None if not index.isValid() else table.frame.iloc[index.row()].get(identity)

    def refresh(self):
        runs, codes = self._assistant.one_off_runs(), self._assistant.reusable_codes()
        self._fill(self.history, runs, {
            "created_at": lambda r: r.get("created_at"), "run_id_text": lambda r: r.get("run_id"),
            "code_hash": lambda r: str(r.get("code_hash") or "")[:12], "repeat_count": lambda r: r.get("repeat_count", 0),
            "review": lambda r: "정식 등록 검토 권장" if r.get("promotion_recommended") else "",
            "status": lambda r: r.get("status"), "origin": lambda r: r.get("origin"),
        }, {"created_at": "실행 시각", "run_id_text": "실행 ID", "code_hash": "코드 해시", "repeat_count": "동일 코드 실행", "review": "검토 상태", "status": "실행 상태", "origin": "출처"}, "run_id")
        self._fill(self.library, codes, {
            "name": lambda r: r.get("name"), "active_version": lambda r: r.get("active_version"),
            "version_count": lambda r: r.get("version_count"), "use_count": lambda r: r.get("use_count"),
            "last_used_at": lambda r: r.get("last_used_at"), "description": lambda r: r.get("description"),
        }, {"name": "등록 이름", "active_version": "버전", "version_count": "버전 수", "use_count": "사용 횟수", "last_used_at": "마지막 사용", "description": "설명"}, "library_id")
        self.status.setText(f"실행 이력 {len(runs):,}건 · 정식 등록 코드 {len(codes):,}건")

    def _register(self):
        run_id = self._selected(self.history, "run_id")
        if not run_id: QMessageBox.information(self, "정식 등록", "1회용 실행 이력을 선택하십시오."); return
        try: code = self._assistant.one_off_code(run_id)
        except Exception as error: QMessageBox.critical(self, "코드 읽기 오류", str(error)); return
        dialog = _RegistrationDialog(code, self)
        if dialog.exec() != QDialog.Accepted: return
        try: row = self._assistant.register_reusable(run_id, dialog.name.text(), dialog.description.text(), dialog.code.toPlainText())
        except Exception as error: QMessageBox.critical(self, "등록 오류", str(error)); return
        self.refresh(); self.status.setText(f"정식 등록 완료: {row['name']} · 버전 {row['active_version']}")

    def _execute(self):
        library_id = self._selected(self.library, "library_id")
        if not library_id: QMessageBox.information(self, "코드 재사용", "정식 등록 코드를 선택하십시오."); return
        text, accepted = QInputDialog.getMultiLineText(self, "등록 코드 재사용", "입력 JSON", "{}")
        if not accepted: return
        try: data = json.loads(text)
        except json.JSONDecodeError as error: QMessageBox.warning(self, "입력 오류", str(error)); return
        self.status.setText("등록 코드를 새 격리 실행에서 수행 중입니다...")
        self._runner.submit(lambda: self._assistant.run_reusable(library_id, data), on_result=self._executed,
                            on_error=lambda trace: QMessageBox.critical(self, "실행 오류", trace.splitlines()[-1]))

    def _executed(self, record):
        self.refresh(); self.status.setText(f"재사용 실행 완료 · 실행 ID {record.run_id}")
        QMessageBox.information(self, "실행 결과", json.dumps(record.result, ensure_ascii=False, indent=2, default=str)[:5000])
