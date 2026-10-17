from __future__ import annotations

import re
from typing import Callable

from PySide6.QtCore import QDate, QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from krx_research.qt.controllers.pattern_search_controller import PatternSearchController
from krx_research.qt.presentation.column_catalog import label_for
from krx_research.qt.presentation.pattern_presenter import PatternResultPresenter
from krx_research.qt.services.box_breakout import PeriodPatternQuery
from krx_research.qt.services.current_pattern import CurrentPatternKind, CurrentPatternQuery
from krx_research.qt.services.pattern_similarity import (
    MovingAverageKind, MovingAverageSpec, PatternSearchQuery,
)
from krx_research.qt.strategies.chart_navigation import SynchronizedChartStrategy
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

    def __init__(self, controller: PatternSearchController, chart_factory: Callable,
                 parent=None):
        super().__init__(parent)
        self._controller, self._chart_factory = controller, chart_factory
        self._thread, self._worker = None, None
        self._charts = []
        self._presenter = PatternResultPresenter()
        self._chart_strategy = SynchronizedChartStrategy(self._create_chart, self._keep_chart)
        self.setWindowTitle("메뉴 3 · 주가 패턴 검색")
        self.resize(1100, 720)
        self._build(); self._mode_changed(0)

    def _build(self) -> None:
        self.mode = QComboBox(); self.mode.addItems((
            "이동평균 유사 패턴", "지정 기간 박스권 패턴",
            CurrentPatternKind.DOUBLE_BOTTOM.value, CurrentPatternKind.CUP_WITH_HANDLE.value,
        ))
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
                              ("", self.volume), ("결과 수", self.top)):
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
        for widget in (self.security, self.start, self.end): widget.setEnabled(index < 2)
        self.help.setText(
            "선택한 종목의 주가와 이동평균선 모양을 같은 기간의 전체 종목과 비교합니다. "
            "지정 기간은 상승 여부와 무관한 기준 모양입니다. 전체 종목의 DB 최신일부터 같은 거래일 수를 비교하고, "
            "비교 종목 중 기간 수익률·추세기울기가 양수이고 종가가 구간 상단 40% 안인 종목만 찾습니다. "
            "2년 내 비정상 가격 단절·과도한 무변동·거래정지·70% 초과 낙폭·장기 바닥 종목은 제외합니다. "
            "최소 5거래일·10% 상승·3일 이상 상승으로 구성된 상승 파동이 한 번 이상 있어야 합니다. "
            "현재 종가>60일선>120일선, 120일선 상승, 60일선 대비 과열 30% 이하를 요구합니다. "
            "SMA·EMA·WMA를 최대 8개 지정하고 이동평균선 모양과 이격도를 함께 비교합니다."
            if similar else (
            "프로그램이 돌파 여부나 돌파일을 판단하지 않습니다. 사용자가 지정한 기준 종목의 전체 기간 "
            "주가·고가·저가·거래량 경로를 기준 모양으로 사용하고, DB 최신일 현재 상승 중인 유사 종목만 찾습니다."
            " 비정상 가격 단절·장기 바닥·과도한 무변동 종목은 결과에서 제외합니다."
            " 단발 급등이 아닌 여러 날의 상승 파동이 최소 한 번 있어야 합니다."
            " 현재 60일·120일 장기 상승 정렬이 아닌 종목도 제외합니다."
            if index == 1 else
            "DB 최신일을 기준으로 전체 종목을 검사합니다. 고정된 한 기간이 아니라 여러 길이의 구조를 비교하여 "
            "형성 중·돌파 대기·최근 돌파 후 구조 유지 단계만 표시합니다. 오래전에 끝났거나 돌파 후 과도하게 "
            "상승한 패턴, 지지선이 훼손된 패턴, 가격 단절·거래 정지 성격의 종목은 제외합니다. "
            "점수와 넥라인·손잡이 상단, 무효화 가격 및 판정 근거는 판단 보조 자료이며 매매 추천이 아닙니다."
            )
        )

    def _suggest_security(self, query: str) -> None:
        try:
            self.security_completer.set_matches(self._controller.suggest_securities(query))
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
        if self.mode.currentIndex() >= 2:
            kind = (CurrentPatternKind.DOUBLE_BOTTOM if self.mode.currentIndex() == 2
                    else CurrentPatternKind.CUP_WITH_HANDLE)
            return self._controller.command(CurrentPatternQuery(kind, self.top.value()))
        start, end = self.start.date().toPython(), self.end.date().toPython()
        security = SecurityCompleter.value(self.security.text())
        if self.mode.currentIndex() == 1:
            query = PeriodPatternQuery(security, start, end, self.top.value())
            return self._controller.command(query)
        periods = tuple(map(int, filter(None, re.split(r"[ ,]+", self.periods.text().strip()))))
        query = PatternSearchQuery(
            security, start, end,
            MovingAverageSpec(MovingAverageKind(self.average.currentText()), periods),
            self.top.value(), True, self.volume.isChecked(),
        )
        return self._controller.command(query)

    @Slot(list)
    def _show_rows(self, rows: list[dict]) -> None:
        frame = self._presenter.present(rows)
        self.table.set_frame(frame, header_labels={column: label_for(column) for column in frame.columns})
        score = "pattern_score" if "pattern_score" in frame else "similarity_pct"
        if score in frame:
            self.table.sortByColumn(frame.columns.get_loc(score), Qt.DescendingOrder)
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
        return self._chart_factory(
            ticker=ticker, quote_venue=quote_venue, parent=parent,
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
