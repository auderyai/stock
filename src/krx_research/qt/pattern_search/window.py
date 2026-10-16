from __future__ import annotations

from pathlib import Path
import re
from typing import Callable

from PySide6.QtCore import QDate, QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from krx_research.database import resolve_database_target
from krx_research.qt.chart_window import ChartWindow
from krx_research.qt.presentation.column_catalog import label_for
from krx_research.qt.presentation.pattern_presenter import PatternResultPresenter
from krx_research.qt.services.chart_service import ChartService
from krx_research.qt.services.box_breakout import PeriodPatternQuery, PeriodPatternSearchService
from krx_research.qt.services.pattern_similarity import (
    MovingAverageKind, MovingAverageSpec, PatternSearchQuery, PatternSimilaritySearchService,
    PatternVectorCache, PostgreSQLPatternRepository,
)
from krx_research.qt.strategies.chart_navigation import SynchronizedChartStrategy
from krx_research.ui.data import WorkstationData
from krx_research.qt.widgets.result_table import ResultTable
from krx_research.qt.widgets.calendar_date_edit import CalendarDateEdit
from krx_research.qt.widgets.security_completer import SecurityCompleter


class SearchWorker(QObject):
    succeeded = Signal(list)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, search: Callable[[], list[dict]]):
        super().__init__(); self._search = search

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self._search())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class PatternSearchDialog(QDialog):
    """Local-only GUI for deterministic similarity and box-breakout searches."""

    def __init__(self, root: Path, parent=None, *, repository=None, chart_service=None):
        super().__init__(parent)
        self._root, self._thread, self._worker = Path(root), None, None
        self._charts = []
        target = resolve_database_target(self._root, read_only=True) if repository is None or chart_service is None else None
        self._repository = repository or PostgreSQLPatternRepository(target)
        self._chart_service = chart_service or ChartService(WorkstationData(target))
        cache = PatternVectorCache(self._root / ".local_cache" / "pattern_vectors")
        self._pattern_service = PatternSimilaritySearchService(self._repository, cache)
        self._period_service = PeriodPatternSearchService(self._repository)
        self._presenter = PatternResultPresenter()
        self._chart_strategy = SynchronizedChartStrategy(self._create_chart, self._keep_chart)
        self.setWindowTitle("메뉴 3 · 주가 패턴 검색")
        self.resize(1100, 720)
        self._build(); self._mode_changed(0)

    def _build(self) -> None:
        self.mode = QComboBox(); self.mode.addItems(("이동평균 유사 패턴", "지정 기간 박스권 패턴"))
        self.security = QLineEdit(); self.security.setPlaceholderText("종목코드 또는 종목명 일부 입력")
        self.security_completer = SecurityCompleter(self.security, self)
        self.security_completer.searchRequested.connect(self._suggest_security)
        today = QDate.currentDate()
        self.start = CalendarDateEdit(today.addMonths(-4))
        self.end = CalendarDateEdit(today)
        self.start.setMaximumDate(today); self.end.setMaximumDate(today)
        self.average = QComboBox(); self.average.addItems(tuple(kind.value for kind in MovingAverageKind))
        self.periods = QLineEdit("5, 20, 60")
        self.periods.setPlaceholderText("2~500일, 최대 8개")
        self.periods.setToolTip("쉼표로 최대 8개를 입력합니다. 예: 5,10,15,33,56,112,224,448")
        self.volume = QCheckBox("거래량 패턴 포함")
        self.top = QSpinBox(); self.top.setRange(1, 100); self.top.setValue(20)
        form = QFormLayout()
        for label, widget in (("검색 종류", self.mode), ("기준 종목", self.security),
                              ("시작일", self.start), ("종료일", self.end),
                              ("이동평균 종류", self.average), ("이동평균 기간", self.periods),
                              ("", self.volume), ("유사 결과 수", self.top)):
            form.addRow(label, widget)
        self.help = QLabel(); self.help.setWordWrap(True)
        self.table = ResultTable()
        self.status = QLabel("조건을 입력한 뒤 검색하십시오.")
        self.search_button = QPushButton("검색")
        self.chart_button = QPushButton("선택 종목 차트"); self.chart_button.setEnabled(False)
        self.close_button = QPushButton("닫기")
        buttons = QHBoxLayout(); buttons.addWidget(self.search_button); buttons.addWidget(self.chart_button)
        buttons.addStretch(1); buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self); layout.addLayout(form); layout.addWidget(self.help)
        layout.addWidget(self.status); layout.addWidget(self.table, 1); layout.addLayout(buttons)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.search_button.clicked.connect(self._search); self.close_button.clicked.connect(self.close)
        self.chart_button.clicked.connect(self._open_chart); self.table.chartRequested.connect(self._open_chart)

    def _mode_changed(self, index: int) -> None:
        similar = index == 0
        for widget in (self.average, self.periods, self.volume): widget.setEnabled(similar)
        self.help.setText(
            "선택한 종목의 주가와 이동평균선 모양을 같은 기간의 전체 종목과 비교합니다. "
            "지정 기간은 기준 모양이며, 전체 종목의 DB 최신일부터 같은 거래일 수의 최근 패턴을 찾습니다. "
            "기간 수익률·추세기울기가 양수이고 종가가 구간 상단 40% 안인 상승 종목만 찾습니다. "
            "SMA·EMA·WMA를 최대 8개 지정하고 이동평균선 모양과 이격도를 함께 비교합니다."
            if similar else
            "프로그램이 돌파 여부나 돌파일을 판단하지 않습니다. 사용자가 지정한 기준 종목의 전체 기간 "
            "주가·고가·저가·거래량 경로를 기준으로 DB 최신일부터 같은 거래일 수의 최근 상승 패턴만 찾습니다."
        )

    def _suggest_security(self, query: str) -> None:
        try:
            self.security_completer.set_matches(self._pattern_service.suggest_securities(query))
        except Exception:
            self.security_completer.set_matches([])

    def _search(self) -> None:
        try:
            search = self._command()
        except Exception as exc:
            QMessageBox.warning(self, "입력 확인", str(exc)); return
        worker, thread = SearchWorker(search), QThread(self)
        worker.moveToThread(thread); thread.started.connect(worker.run)
        worker.succeeded.connect(self._show_rows); worker.failed.connect(self._failed)
        worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater); thread.finished.connect(self._finished)
        self._worker, self._thread = worker, thread
        self.search_button.setEnabled(False); self.close_button.setEnabled(False)
        self.status.setText("로컬 DB에서 검색 중..."); thread.start()

    def _command(self) -> Callable[[], list[dict]]:
        start, end = self.start.date().toPython(), self.end.date().toPython()
        security = SecurityCompleter.value(self.security.text())
        if self.mode.currentIndex() == 1:
            query = PeriodPatternQuery(security, start, end, self.top.value())
            return lambda: self._period_service.search(query)
        periods = tuple(map(int, filter(None, re.split(r"[ ,]+", self.periods.text().strip()))))
        query = PatternSearchQuery(
            security, start, end,
            MovingAverageSpec(MovingAverageKind(self.average.currentText()), periods),
            self.top.value(), True, self.volume.isChecked(),
        )
        return lambda: self._pattern_service.search(query)

    @Slot(list)
    def _show_rows(self, rows: list[dict]) -> None:
        frame = self._presenter.present(rows)
        self.table.set_frame(frame, header_labels={column: label_for(column) for column in frame.columns})
        if "similarity_pct" in frame:
            self.table.sortByColumn(frame.columns.get_loc("similarity_pct"), Qt.DescendingOrder)
        self.chart_button.setEnabled(not frame.empty)
        self.status.setText(f"검색 완료: {len(frame)}종목")

    def _open_chart(self, *_args) -> None:
        ticker = self.table.current_ticker()
        if not ticker:
            QMessageBox.information(self, "차트", "결과 종목을 선택하십시오."); return
        frame = self.table.frame.copy()
        self._chart_strategy.open(
            ticker=ticker, quote_venue="KRX", parent=self, frame=frame,
            labels={column: label_for(column) for column in frame.columns},
        )

    def _create_chart(self, *, ticker: str, quote_venue: str, parent,
                      navigation_enabled: bool, navigation_frame=None, navigation_labels=None):
        return ChartWindow(
            self._chart_service, ticker, quote_venue=quote_venue, parent=parent,
            navigation_enabled=navigation_enabled, navigation_frame=navigation_frame,
            navigation_labels=navigation_labels,
        )

    def _keep_chart(self, chart):
        self._charts.append(chart)
        chart.destroyed.connect(lambda _=None, item=chart: self._charts.remove(item) if item in self._charts else None)
        chart.show()
        return chart

    @Slot(str)
    def _failed(self, message: str) -> None:
        self.status.setText("검색 실패"); QMessageBox.critical(self, "검색 오류", message)

    def _finished(self) -> None:
        self._thread = self._worker = None
        self.search_button.setEnabled(True); self.close_button.setEnabled(True)

    def closeEvent(self, event) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.status.setText("검색이 끝난 뒤 창을 닫을 수 있습니다."); event.ignore(); return
        super().closeEvent(event)
