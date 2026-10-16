from __future__ import annotations

import datetime as dt
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from krx_research.application.job_menu.models import JobKind, JobRequest, LegacyJobSpec
from krx_research.database import resolve_database_target
from krx_research.qt.services.security_search_service import SecuritySearchService
from krx_research.qt.widgets.calendar_date_edit import CalendarDateEdit
from krx_research.qt.widgets.security_completer import SecurityCompleter
from krx_research.ui.data import WorkstationData
from .controller import JobMenuController


@dataclass(frozen=True)
class UiJob:
    number: int
    title: str
    description: str
    integrated: bool
    legacy: LegacyJobSpec | None = None


class RangeDialog(QDialog):
    def __init__(self, title: str, *, menu: int, security_search: Callable,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._menu = menu
        today = QDate.currentDate()
        self.start = CalendarDateEdit(today.addDays(-7))
        self.end = CalendarDateEdit(today)
        self.start.setMaximumDate(today); self.end.setMaximumDate(today)
        self.ticker = QLineEdit()
        self.ticker.setPlaceholderText("선택: 종목코드 또는 종목명 일부 입력, 비우면 전체")
        self._security_search = security_search
        self.ticker_completer = SecurityCompleter(self.ticker, self)
        self.ticker_completer.searchRequested.connect(self._suggest_security)
        self.chunk = QSpinBox()
        self.chunk.setRange(1, 90)
        self.chunk.setValue(90)
        self.nxt = QCheckBox("NXT")
        self.combined = QCheckBox("COMBINED")
        self.nxt.setChecked(True)
        self.combined.setChecked(True)
        self.investor = QCheckBox("수급(t1702) 포함")
        self.investor.setChecked(True)
        form = QFormLayout()
        form.addRow("시작일", self.start)
        form.addRow("종료일", self.end)
        form.addRow("종목", self.ticker)
        if menu == 5:
            form.addRow("구간 일수", self.chunk)
        if menu == 7:
            venues = QHBoxLayout(); venues.addWidget(self.nxt); venues.addWidget(self.combined)
            box = QWidget(); box.setLayout(venues)
            form.addRow("거래시장", box)
            form.addRow("", self.investor)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self); layout.addLayout(form); layout.addWidget(buttons)

    def _suggest_security(self, query: str) -> None:
        try:
            self.ticker_completer.set_matches(self._security_search(query, limit=20))
        except Exception:
            self.ticker_completer.set_matches([])

    def request(self) -> JobRequest:
        start = self.start.date().toPython()
        end = self.end.date().toPython()
        ticker = SecurityCompleter.value(self.ticker.text()) or None
        if self._menu == 5:
            return JobRequest(JobKind.MENU_5, start=start, end=end, ticker=ticker,
                              chunk_days=self.chunk.value())
        venues = tuple(v for v, checked in (("NXT", self.nxt.isChecked()),
                                             ("COMBINED", self.combined.isChecked())) if checked)
        return JobRequest(JobKind.MENU_7, start=start, end=end, ticker=ticker,
                          venues=venues, include_investor=self.investor.isChecked())


class DateDialog(QDialog):
    def __init__(self, title: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.date = CalendarDateEdit(QDate.currentDate())
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        form = QFormLayout(self); form.addRow(label, self.date); form.addRow(buttons)

    def value(self) -> dt.date:
        return self.date.date().toPython()


class KrxJobMenuWindow(QMainWindow):
    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self._root = project_root
        self._controller = JobMenuController(project_root, self)
        self._jobs = self._load_jobs()
        self.setWindowTitle("KRX 작업 메뉴 · PySide6 V42")
        self.resize(820, 620)
        self._build()
        self._wire()

    def _build(self) -> None:
        root = QWidget(); self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel("KRX 작업 메뉴")
        font = title.font(); font.setPointSize(16); font.setBold(True); title.setFont(font)
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "메뉴 2는 로컬 갱신, 메뉴 3은 주가 패턴 검색, 메뉴 5·7은 LS 수집, 메뉴 8·9·10은 Drive 관리입니다."
        ))
        self.list = QListWidget()
        for job in self._jobs:
            item = QListWidgetItem(f"{job.number}. {job.title}")
            item.setData(Qt.UserRole, job)
            self.list.addItem(item)
        layout.addWidget(self.list)
        self.description = QLabel("")
        self.description.setWordWrap(True); layout.addWidget(self.description)
        self.status = QLabel("대기"); layout.addWidget(self.status)
        self.log = QTextEdit(); self.log.setReadOnly(True); self.log.document().setMaximumBlockCount(5000)
        self._pending_log: list[str] = []; self._log_timer = QTimer(self); self._log_timer.setInterval(100)
        self._log_timer.timeout.connect(self._flush_log); self._log_timer.start(); layout.addWidget(self.log, 1)
        row = QHBoxLayout()
        self.run_button = QPushButton("실행")
        self.stop_button = QPushButton("중지"); self.stop_button.setEnabled(False)
        self.close_button = QPushButton("닫기")
        row.addWidget(self.run_button); row.addWidget(self.stop_button); row.addStretch(1); row.addWidget(self.close_button)
        layout.addLayout(row)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _wire(self) -> None:
        self.list.currentItemChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(lambda _item: self._run_selected())
        self.run_button.clicked.connect(self._run_selected)
        self.stop_button.clicked.connect(self._controller.cancel)
        self.close_button.clicked.connect(self.close)
        self._controller.progress.connect(self._queue_log)
        self._controller.status_changed.connect(self.status.setText)
        self._controller.completed.connect(self._done)
        self._controller.failed.connect(self._failed)
        self._controller.busy_changed.connect(self._busy)
        self._selection_changed(self.list.currentItem(), None)

    def _selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        job = current.data(Qt.UserRole) if current else None
        self.description.setText(job.description if job else "")

    def _run_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        job: UiJob = item.data(Qt.UserRole)
        self.log.clear()
        if job.number == 3:
            from krx_research.qt.pattern_search import PatternSearchDialog
            PatternSearchDialog(self._root, self).exec()
            return
        if not job.integrated:
            if job.legacy is None:
                QMessageBox.warning(self, "실행 불가", "기존 작업 실행정보가 없습니다.")
                return
            self._controller.run_legacy(job.legacy)
            return
        if job.number in {8, 9}:
            self._controller.run(JobRequest(JobKind(job.number)))
            return
        if job.number in {2, 10}:
            cleanup = job.number == 10
            dialog = DateDialog(
                job.title, "정리 기준일" if cleanup else "기준일", self
            )
            if dialog.exec() != QDialog.Accepted:
                return
            if cleanup and QMessageBox.warning(
                self,
                "Drive 자료 정리 확인",
                "로컬 반영과 메뉴 7 완료가 검증된 날짜까지만 Drive 자료를 삭제합니다. 계속하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            self._controller.run(JobRequest(JobKind(job.number), end=dialog.value()))
            return
        security_search = SecuritySearchService(
            WorkstationData(resolve_database_target(self._root, read_only=True))
        )
        range_dialog = RangeDialog(
            job.title, menu=job.number, security_search=security_search.search, parent=self
        )
        if range_dialog.exec() == QDialog.Accepted:
            self._controller.run(range_dialog.request())

    def _busy(self, busy: bool) -> None:
        if not busy: self._flush_log()
        self.run_button.setEnabled(not busy)
        self.list.setEnabled(not busy)
        self.stop_button.setEnabled(busy)

    def _done(self, message: str) -> None:
        self._flush_log(); self.log.append("\n[COMPLETE] " + message); self.status.setText("완료")

    def _failed(self, message: str) -> None:
        self._flush_log(); self.log.append("\n[FAIL] " + message); self.status.setText("오류 종료")

    def _queue_log(self, message: str) -> None:
        self._pending_log.append(message)

    def _flush_log(self) -> None:
        if self._pending_log:
            self.log.append("\n".join(self._pending_log)); self._pending_log.clear()

    def _load_jobs(self) -> list[UiJob]:
        legacy = self._load_legacy()
        by_number: dict[int, UiJob] = {}
        for spec in legacy:
            number = self._number_from_title(spec.title)
            if number is not None:
                by_number[number] = UiJob(number, self._strip_number(spec.title), spec.description, False, spec)
        by_number[2] = UiJob(2, "당일 데이터 갱신 (장 마감 후)",
                             "기존 KRX 일일 파이프라인 후 t8424/t8436/t1516/t8429를 PostgreSQL에 통합 저장합니다.", True)
        by_number[3] = UiJob(3, "주가·이동평균 패턴 검색",
                             "전체 종목에서 이동평균 유사 패턴 또는 지정 기간 박스권 패턴을 로컬 DB로 검색합니다.", True)
        by_number[5] = UiJob(5, "LS 수급 원본 갱신 (날짜 지정)",
                             "t1702는 LS OPEN API 우선, 실패 요청만 Xing fallback으로 PostgreSQL에 저장합니다.", True)
        by_number[7] = UiJob(7, "LS 종목별 일봉·수급 원본 보완",
                             "t8451/t1702는 LS OPEN API 우선·Xing fallback으로 PostgreSQL 누락분만 보완합니다.", True)
        by_number[8] = UiJob(8, "Google Drive 작업 상태 확인",
                             "비밀값을 출력하지 않고 Drive 상태·체크포인트·암호화 자료 무결성을 검증합니다.", True)
        by_number[9] = UiJob(9, "Google Drive 자료 로컬 반영",
                             "Drive 변경분을 PostgreSQL에 멱등 반영하고 재실행하여 already_applied를 검증합니다.", True)
        by_number[10] = UiJob(10, "반영 완료 Google Drive 자료 정리",
                              "로컬 반영과 메뉴 7 완료가 검증된 기준일까지 파일과 메타데이터를 함께 정리합니다.", True)
        if 1 not in by_number:
            by_number[1] = UiJob(1, "KRX 워크스테이션 GUI 실행",
                                 "종목 검색, 차트 및 분석 화면을 실행합니다.", False,
                                 LegacyJobSpec("gui", "1. KRX 워크스테이션 GUI 실행",
                                               "종목 검색, 차트 및 분석 화면을 실행합니다.",
                                               "run_workstation_gui.bat"))
        return [by_number[n] for n in sorted(by_number)]

    def _load_legacy(self) -> list[LegacyJobSpec]:
        path = self._root / "config" / "v42_legacy_jobs.json"
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        result: list[LegacyJobSpec] = []
        for row in data if isinstance(data, list) else []:
            try:
                result.append(LegacyJobSpec(
                    str(row.get("key", "legacy")), str(row["title"]), str(row.get("description", "")),
                    str(row.get("batch_name", "")), tuple(str(x) for x in row.get("arguments", [])),
                ))
            except Exception:
                continue
        return result

    @staticmethod
    def _number_from_title(title: str) -> int | None:
        head = title.strip().split(".", 1)[0]
        return int(head) if head.isdigit() else None

    @staticmethod
    def _strip_number(title: str) -> str:
        parts = title.split(".", 1)
        return parts[1].strip() if len(parts) == 2 and parts[0].strip().isdigit() else title


def find_project_root() -> Path:
    """Return canonical C:\stock project root."""
    root = Path(r"C:\stock")
    required = (
        root / "src" / "krx_research",
        root / "scripts",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(
            "C:\\stock project root validation failed. Missing: "
            + ", ".join(missing)
        )
    return root


def main() -> int:
    """Launch KRX Job Menu visibly on the active desktop."""
    from pathlib import Path

    runtime_log = Path(r"C:\stock\logs\runtime\run_krx_menu_runtime.log")

    def _runtime_log(message: str) -> None:
        try:
            with runtime_log.open("a", encoding="utf-8") as fh:
                fh.write(message + "\n")
        except Exception:
            pass

    _runtime_log("[GUI] main entered")

    app = QApplication.instance() or QApplication(sys.argv)
    _runtime_log(f"[GUI] QApplication ready screens={len(app.screens())}")

    for idx, screen in enumerate(app.screens()):
        geo = screen.availableGeometry()
        _runtime_log(
            f"[GUI] screen[{idx}] name={screen.name()} "
            f"available=({geo.x()},{geo.y()},{geo.width()},{geo.height()})"
        )

    root = find_project_root()
    _runtime_log(f"[GUI] project_root={root}")

    window = KrxJobMenuWindow(root)
    _runtime_log("[GUI] window constructed")

    window.showNormal()
    window.show()

    primary = app.primaryScreen()
    if primary is not None:
        screen_geo = primary.availableGeometry()
        frame = window.frameGeometry()
        frame.moveCenter(screen_geo.center())
        window.move(frame.topLeft())
        _runtime_log(
            f"[GUI] centered_on_primary x={window.x()} y={window.y()} "
            f"w={window.width()} h={window.height()}"
        )

    try:
        window.raise_()
    except Exception:
        pass

    try:
        window.activateWindow()
    except Exception:
        pass

    app.processEvents()

    _runtime_log(
        f"[GUI] visible={window.isVisible()} "
        f"active={window.isActiveWindow()} "
        f"geometry=({window.x()},{window.y()},{window.width()},{window.height()})"
    )
    _runtime_log("[GUI] entering event loop")

    rc = app.exec()
    _runtime_log(f"[GUI] event loop exited rc={rc}")
    return int(rc)
