from __future__ import annotations

from datetime import date
from dataclasses import asdict
from html import escape

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSpinBox,
    QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser,
    QVBoxLayout, QWidget,
)

from krx_research_nextgen.controllers.main_window_controller import MainWindowController
from krx_research_nextgen.controllers.screening_controller import ScreeningController
from krx_research_nextgen.models.screen_catalog import SCREENS, ScreenSpec
from krx_research_nextgen.models.screening import DateRange, ScreeningKind, ScreeningResult
from krx_research_nextgen.presentation.screening_table import HEADERS, row_values
from krx_research_nextgen.presentation.ai_result_table import AiResultPresenter
from krx_research_nextgen.windows.chart_window import ChartWindow
from krx_research_nextgen.windows.scenario_window import ScenarioWindow
from krx_research_nextgen.windows.repeated_screen_window import RepeatedScreenWindow
from krx_research_nextgen.workers.task_runner import TaskRunner
from krx_research_nextgen.widgets.calendar_date_edit import CalendarDateEdit
from krx_research_nextgen.windows.research_archive_window import ResearchArchiveWindow
from krx_research_nextgen.windows.daily_research_window import DailyResearchWindow, SPECS
from krx_research_nextgen.windows.reusable_code_window import ReusableCodeWindow
from krx_research.qt.presentation.error_presenter import user_friendly_error


class Stage4MainWindow(QMainWindow):
    """Legacy-compatible PyQt6 View; all data comes through controllers."""

    def __init__(self, main_controller: MainWindowController, screening_controller: ScreeningController, auxiliary_controller, assistant_service) -> None:
        super().__init__()
        self._main, self._screening, self._auxiliary = main_controller, screening_controller, auxiliary_controller
        self._assistant = assistant_service
        self._assistant.bind_numbered_screen_runner(self._run_numbered_screen)
        self._tasks = TaskRunner(self)
        self._results: list[ScreeningResult] = []
        self._table_navigation = None
        self._current_code = ""
        self._result_ticker_column = 2
        self._comparison_code = "005930"
        self._chart_window: ChartWindow | None = None
        self._sync_chart_window: ChartWindow | None = None
        self._chart_windows: list[ChartWindow] = []
        self._scenario_windows: list[ScenarioWindow] = []
        self._repeated_windows: list[RepeatedScreenWindow] = []
        self._research_windows: list[ResearchArchiveWindow] = []
        self._daily_research_windows: list[DailyResearchWindow] = []
        self._code_library_window: ReusableCodeWindow | None = None
        self._navigation_context = None
        self._active_task_title = "종목 차트"
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True); self._search_timer.setInterval(250)
        self.setWindowTitle("KRX Stock · PyQt6 · PostgreSQL")
        self.resize(1720, 1000)
        self._build(); self._connect(); self._load_status()

    def _build(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self); self.setCentralWidget(splitter)
        left = QWidget(); left_layout = QVBoxLayout(left)
        title = QLabel("Stock · PyQt6"); title.setStyleSheet("font-size:18px;font-weight:700")
        left_layout.addWidget(title); left_layout.addWidget(QLabel("데이터베이스: PostgreSQL 전용 · C:\\stock\\.env 기준"))

        query = QGroupBox("조회 조건"); grid = QGridLayout(query)
        self.source = QComboBox(); self.source.addItem("데이터베이스")
        self.market = QComboBox(); self.market.addItems(["KRX", "NXT", "KRX+NXT"])
        self.start_date = CalendarDateEdit(); self.end_date = CalendarDateEdit()
        self.rank_limit = QSpinBox(); self.rank_limit.setRange(1, 500); self.rank_limit.setValue(50); self.rank_limit.setSuffix(" 위")
        for row, pair in enumerate((("자료", self.source), ("시장", self.market), ("시작", self.start_date), ("종료", self.end_date), ("출력 순위", self.rank_limit))):
            grid.addWidget(QLabel(pair[0]), row, 0); grid.addWidget(pair[1], row, 1)
        left_layout.addWidget(query)

        near = QGroupBox("52주 최고가 대비 종가 (%)"); near_row = QHBoxLayout(near)
        self.near_low = QDoubleSpinBox(); self.near_low.setRange(-100, 100); self.near_low.setValue(-10); self.near_low.setSuffix(" %")
        self.near_high = QDoubleSpinBox(); self.near_high.setRange(-100, 100); self.near_high.setSuffix(" %")
        self.near_button = QPushButton("구간 검색")
        near_row.addWidget(self.near_low); near_row.addWidget(QLabel("~")); near_row.addWidget(self.near_high); near_row.addWidget(self.near_button)
        left_layout.addWidget(near)

        search = QGroupBox("종목 검색 · 이동평균 유사배열 기준 종목"); search_layout = QVBoxLayout(search)
        search_row = QHBoxLayout(); self.search_edit = QLineEdit(); self.search_edit.setPlaceholderText("종목명 또는 6자리 종목코드")
        self.search_button = QPushButton("종목 찾기"); search_row.addWidget(self.search_edit, 1); search_row.addWidget(self.search_button)
        search_layout.addLayout(search_row)
        self.search_list = QListWidget(); self.search_list.setMaximumHeight(110); search_layout.addWidget(self.search_list)
        self.comparison = QLabel("기준 종목: 선택되지 않음"); search_layout.addWidget(self.comparison)
        search_buttons = QHBoxLayout(); self.search_chart = QPushButton("차트 열기"); self.use_comparison = QPushButton("유사배열 기준종목으로 사용")
        search_buttons.addWidget(self.search_chart); search_buttons.addWidget(self.use_comparison); search_layout.addLayout(search_buttons)
        left_layout.addWidget(search)

        self.screen_list = QListWidget()
        for number, spec in enumerate(SCREENS, 1): self.screen_list.addItem(f"{number}. {spec.title}")
        left_layout.addWidget(self.screen_list, 1)
        buttons = QGridLayout(); self.run_button = QPushButton("선택 항목 조회 실행"); buttons.addWidget(self.run_button, 0, 0, 1, 2)
        self.repeated_button = QPushButton("기간 내 다빈도 종목"); buttons.addWidget(self.repeated_button, 1, 0, 1, 2)
        actions = (("수급 대시보드", self._open_investor), ("종합·업종 지수", self._open_market_index),
                   ("일일 특징주", lambda: self._open_daily_research("featured")),
                   ("일일 테마", lambda: self._open_daily_research("theme")),
                   ("리포트·이미지 자료", self._open_research_archive))
        self.auxiliary_buttons = []
        for pos, (label, action) in enumerate(actions):
            button = QPushButton(label); button.clicked.connect(action); self.auxiliary_buttons.append(button)
            if pos < 2: button.setEnabled(False)
            if pos == len(actions) - 1: buttons.addWidget(button, 4, 0, 1, 2)
            else: buttons.addWidget(button, 2 + pos // 2, pos % 2)
        left_layout.addLayout(buttons); splitter.addWidget(left)

        right = QWidget(); right_layout = QVBoxLayout(right); top = QHBoxLayout()
        self.heading = QLabel("스크리닝 항목을 선택하십시오."); self.heading.setStyleSheet("font-size:15px;font-weight:700")
        self.sync_chart = QCheckBox("결과목록 탐색 · 같은 차트 갱신")
        self.export_button = QPushButton("결과 엑셀 저장")
        self.chart_button = QPushButton("선택 종목 차트")
        top.addWidget(self.heading, 1); top.addWidget(self.sync_chart); top.addWidget(self.export_button); top.addWidget(self.chart_button)
        right_layout.addLayout(top)
        self.result_table = QTableWidget(0, len(HEADERS))
        self.result_table.setHorizontalHeaderLabels(HEADERS)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.result_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_table.setAlternatingRowColors(True); self.result_table.verticalHeader().setVisible(False)
        self.result_table.horizontalHeader().setSectionsMovable(True)
        for col in range(self.result_table.columnCount()):
            self.result_table.horizontalHeaderItem(col).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        content = QSplitter(Qt.Orientation.Vertical); content.addWidget(self.result_table)
        assistant = QWidget(); assistant_layout = QVBoxLayout(assistant)
        assistant_layout.addWidget(QLabel("Codex 구독 분석 대화 · Stock DB 값 우선 · 연구자료 검색 · 1회용 코드 격리"))
        self.ai_conversation = QTextBrowser(); self.ai_conversation.setOpenExternalLinks(True); assistant_layout.addWidget(self.ai_conversation, 1)
        self.ai_prompt = QPlainTextEdit(); self.ai_prompt.setMaximumHeight(75)
        self.ai_prompt.setPlaceholderText("DB·보관 리포트·Stock 파일·차트·최신 웹 자료를 요청하십시오."); assistant_layout.addWidget(self.ai_prompt)
        ai_actions = QHBoxLayout(); self.ai_codes = QPushButton("1회용 코드 관리"); ai_actions.addWidget(self.ai_codes); ai_actions.addStretch(1); self.ai_clear = QPushButton("대화 지우기"); self.ai_send = QPushButton("전송")
        ai_actions.addWidget(self.ai_clear); ai_actions.addWidget(self.ai_send); assistant_layout.addLayout(ai_actions)
        content.addWidget(assistant); content.setSizes([650, 250]); right_layout.addWidget(content, 1)
        self.status = QLabel(""); self.status.setWordWrap(True); right_layout.addWidget(self.status)
        splitter.addWidget(right); splitter.setSizes([450, 1270])

    def _connect(self) -> None:
        self.search_button.clicked.connect(self._search_now); self.search_edit.returnPressed.connect(self._search_now)
        self.search_edit.textChanged.connect(self._search_timer.start); self._search_timer.timeout.connect(self._search_now)
        self.run_button.clicked.connect(self._run_selected); self.screen_list.itemDoubleClicked.connect(lambda _: self._run_selected())
        self.repeated_button.clicked.connect(self._run_repeated)
        self.chart_button.clicked.connect(self._open_selected_chart); self.result_table.itemDoubleClicked.connect(lambda _: self._open_selected_chart())
        self.result_table.itemSelectionChanged.connect(self._sync_selection)
        self.search_chart.clicked.connect(self._open_search_chart); self.search_list.itemDoubleClicked.connect(lambda _: self._open_search_chart())
        self.use_comparison.clicked.connect(self._set_comparison); self.near_button.clicked.connect(self._run_near_high)
        self.export_button.clicked.connect(self._export_results)
        self.ai_send.clicked.connect(self._ask_assistant); self.ai_clear.clicked.connect(self._clear_assistant); self.ai_codes.clicked.connect(self._open_code_library)

    def _load_status(self) -> None:
        self.status.setText("PostgreSQL 최신일을 확인하는 중입니다...")
        self._tasks.submit(self._screening.status, on_result=self._status_ready,
                           on_error=self._status_failed, channel="status")

    def _status_ready(self, status) -> None:
        earliest, latest = str(status["earliest_trade_date"]), str(status["latest_trade_date"])
        dates = [str(value) for value in status.get("trade_dates", ())]
        if not dates:
            self._status_failed("PostgreSQL에 선택 가능한 거래일이 없습니다.")
            return
        bounds = date.fromisoformat(min(dates)), date.fromisoformat(max(dates))
        for editor in (self.start_date, self.end_date): editor.set_bounds(*bounds)
        self.status.setText(f"PostgreSQL · DB 기간 {earliest} ~ {latest}")
        for button in self.auxiliary_buttons[:2]: button.setEnabled(True)

    def _status_failed(self, trace: str) -> None:
        self.status.setText(f"상태 확인 실패: {self._trace_message(trace)}")
        for button in self.auxiliary_buttons[:2]: button.setEnabled(True)

    def _search_now(self) -> None:
        keyword = self.search_edit.text().strip()
        self._tasks.submit(lambda: self._main.search_securities(keyword, limit=30), on_result=self._search_ready,
                           on_error=lambda trace: self._show_error("종목 검색 오류", trace), channel="search")

    def _search_ready(self, rows) -> None:
        self.search_list.clear()
        for item in rows:
            row = QListWidgetItem(f"{item.stock_code}  {item.stock_name}  [{item.market}]")
            row.setData(Qt.ItemDataRole.UserRole, item.stock_code); self.search_list.addItem(row)
        if rows: self.search_list.setCurrentRow(0)
        self.status.setText(f"종목 검색 결과 {len(rows):,}건")

    def _selected_spec(self) -> ScreenSpec | None:
        row = self.screen_list.currentRow(); return SCREENS[row] if 0 <= row < len(SCREENS) else None

    def _run_selected(self) -> None:
        spec = self._selected_spec()
        if not spec: QMessageBox.information(self, "조회", "스크리닝 항목을 선택하십시오."); return
        self._run_screening(spec.kind, self.rank_limit.value(), spec.market, spec.title)

    def _run_numbered_screen(self, number: int, period: tuple[date, date], limit: int) -> tuple[str, list[dict]]:
        if number < 1 or number > len(SCREENS):
            raise ValueError(f"화면 항목 번호는 1~{len(SCREENS)}만 허용합니다.")
        spec = SCREENS[number - 1]
        if spec.kind is None:
            raise ValueError(f"{number}번 항목은 실행할 수 없습니다.")
        selected = DateRange(*period)
        rows = self._screening.run(
            spec.kind, limit=limit, market=spec.market,
            comparison_ticker=self._comparison_code, as_of_date=selected.end.isoformat(),
            period=selected,
        )
        return (
            f"{number}. {spec.title} {limit} · {selected.start} ~ {selected.end}",
            [asdict(row) for row in rows],
        )

    def _run_screening(self, kind: ScreeningKind, limit: int, market: str, title: str | None = None) -> None:
        period = self._checked_period()
        if period is None: return
        self.run_button.setEnabled(False); self.status.setText("스크리닝 조회 중입니다...")
        date = period.end.isoformat()
        comparison, near_low, near_high = self._comparison_code, self.near_low.value(), self.near_high.value()
        self._tasks.submit(
            lambda: self._screening.run(
                kind, limit=limit, market=market,
                comparison_ticker=comparison, near_low=near_low, near_high=near_high,
                as_of_date=date, period=period,
            ),
            on_result=lambda rows: self._screening_ready(rows, title or kind.value, period),
            on_error=lambda trace: self._show_error("스크리닝 오류", trace),
            on_finished=lambda: self.run_button.setEnabled(True), channel="screening",
        )

    def _screening_ready(self, rows, title: str, period: DateRange) -> None:
        self._active_task_title = f"{title} · 데이터베이스"
        self._results = rows; self._table_navigation = None
        self._populate_screening(rows); self.heading.setText(self._active_task_title)
        self.status.setText(
            f"{len(rows):,}개 종목 · PostgreSQL · 선택기간 {period.start} ~ {period.end} · "
            f"판정기준일 {period.end}"
        )

    def _run_near_high(self) -> None:
        self._run_screening(ScreeningKind.NEAR_HIGH_52W, self.rank_limit.value(), "ALL", "52주 최고가 대비 종가 구간")

    def _run_repeated(self) -> None:
        spec, period = self._selected_spec(), self._checked_period()
        if not spec: QMessageBox.information(self, "조회", "스크리닝 항목을 선택하십시오."); return
        if period is None or spec.kind is None: return
        self.repeated_button.setEnabled(False); self.status.setText("기간 내 다빈도 종목을 집계하는 중입니다...")
        comparison, low, high = self._comparison_code, self.near_low.value(), self.near_high.value()
        self._tasks.submit(
            lambda: self._screening.run_repeated(spec.kind, period, limit=self.rank_limit.value(), market=spec.market,
                                                  comparison_ticker=comparison, near_low=low, near_high=high),
            on_result=lambda rows: self._repeated_ready(rows, spec.title, period),
            on_error=lambda trace: self._show_error("기간 내 다빈도 종목 오류", trace),
            on_finished=lambda: self.repeated_button.setEnabled(True), channel="repeated-screening",
        )

    def _repeated_ready(self, rows, title: str, period: DateRange) -> None:
        window = RepeatedScreenWindow(self._screening, rows, title, period, self)
        window.stock_requested.connect(self.open_stock_chart); self._repeated_windows.append(window)
        window.destroyed.connect(lambda _=None, w=window: self._repeated_windows.remove(w) if w in self._repeated_windows else None)
        window.show(); window.raise_(); self.status.setText(f"기간 내 2회 이상 등장 종목 {len(rows):,}개")

    def _populate_screening(self, rows: list[ScreeningResult]) -> None:
        self._result_ticker_column = 2
        self.result_table.clear(); self.result_table.setColumnCount(len(HEADERS)); self.result_table.setHorizontalHeaderLabels(HEADERS)
        self.result_table.setRowCount(len(rows))
        for col in range(self.result_table.columnCount()): self.result_table.horizontalHeaderItem(col).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        for row, item in enumerate(rows):
            values = row_values(item)
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter if col in (0, 2) else
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter if col in (1, 5, 6, 7, 8, 9, 10, 11, 12, 14) else
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                self.result_table.setItem(row, col, cell)
        if rows: self.result_table.selectRow(0)
        self.result_table.resizeColumnsToContents()

    def _export_results(self) -> None:
        if not self._results: return
        path, _ = QFileDialog.getSaveFileName(self, "결과 엑셀 저장", "screening_results.xlsx", "Excel (*.xlsx)")
        if path:
            self.status.setText("결과 Excel 저장 중입니다...")
            self._tasks.submit(lambda: self._screening.export(self._results, path),
                               on_result=lambda _: self.status.setText(f"결과 엑셀 저장 완료: {path}"),
                               on_error=lambda trace: self._show_error("결과 엑셀 저장 오류", trace), channel="export")

    def _selected_result_code(self) -> str:
        row = self.result_table.currentRow()
        item = self.result_table.item(row, self._result_ticker_column) if row >= 0 and self._result_ticker_column >= 0 else None
        return item.text() if item else ""

    def _open_selected_chart(self) -> None:
        self._navigation_context = self._table_navigation
        self._open_chart(self._selected_result_code(), self._active_task_title)
    def _open_search_chart(self) -> None:
        item = self.search_list.currentItem()
        if item: self._navigation_context = None; self._open_chart(str(item.data(Qt.ItemDataRole.UserRole)), "종목 검색")

    def _open_chart(self, code: str, task_title: str | None = None) -> None:
        if not code: return
        if task_title: self._active_task_title = task_title
        if self.sync_chart.isChecked():
            if self._sync_chart_window is None: self._sync_chart_window = self._new_chart_window(True)
            window = self._sync_chart_window
        else:
            window = self._new_chart_window(False); self._chart_windows.append(window)
        self._chart_window = window; window.status.setText(f"{code} 차트 자료를 불러오는 중입니다...")
        window.show(); window.raise_(); self._current_code = code
        navigation = self._navigation_context
        title = self._active_task_title
        self._tasks.submit(lambda: self._main.prepare_chart(code, limit=500),
                           on_result=lambda bundle,w=window,c=code,n=navigation,t=title: self._chart_ready(w, c, bundle, n, t),
                           on_error=lambda trace: self._show_error(f"{code} 차트 오류", trace),
                           channel=f"chart:{id(window)}")

    def open_stock_chart(self, code: str, navigation) -> None:
        self._navigation_context = navigation; self._open_chart(code, navigation.get("title", "수급 대시보드"))

    def _chart_ready(self, window, code: str, bundle, navigation=None, task_title: str | None = None) -> None:
        if not window.isVisible(): return
        window.show_bundle(code, bundle, task_title)
        if window is self._sync_chart_window:
            if navigation: window.set_navigation_data(navigation["headers"], navigation["items"], code, navigation.get("alignments"))
            else: window.set_navigation(self._results, code)

    def _new_chart_window(self, navigation: bool) -> ChartWindow:
        window = ChartWindow(navigation)
        window.reload_requested.connect(self._reload_chart); window.ticker_changed.connect(self._open_chart)
        window.scenario_requested.connect(self._open_scenario)
        window.destroyed.connect(lambda _=None, w=window: self._chart_windows.remove(w) if w in self._chart_windows else None)
        return window

    def _open_scenario(self, frame, code: str) -> None:
        window = ScenarioWindow(self._main, frame, code, self)
        self._scenario_windows.append(window)
        window.destroyed.connect(lambda _=None, w=window: self._scenario_windows.remove(w) if w in self._scenario_windows else None)
        window.show(); window.raise_()

    def _reload_chart(self, code: str, limit: int, _profile: int, timeframe: str) -> None:
        window = self.sender()
        if isinstance(window, ChartWindow):
            window.status.setText(f"{code} 차트 자료를 다시 불러오는 중입니다...")
            self._tasks.submit(lambda: self._main.prepare_chart(code, limit=limit, timeframe=timeframe),
                               on_result=lambda bundle,w=window,c=code: w.show_bundle(c, bundle),
                               on_error=lambda trace: self._show_error(f"{code} 차트 오류", trace),
                               channel=f"chart:{id(window)}")

    def _sync_selection(self) -> None:
        if self.sync_chart.isChecked() and self._sync_chart_window and self._sync_chart_window.isVisible():
            self._navigation_context = self._table_navigation; self._open_chart(self._selected_result_code())

    def _set_comparison(self) -> None:
        item = self.search_list.currentItem()
        if item:
            self._comparison_code = str(item.data(Qt.ItemDataRole.UserRole))
            self.comparison.setText("기준 종목: " + item.text())

    def _open_investor(self) -> None:
        period = self._checked_period()
        if period: self._auxiliary.open_investor(self, period.start, period.end)

    def _open_market_index(self) -> None: self._auxiliary.open_market_index(self)

    def _open_daily_research(self, kind: str) -> None:
        window = DailyResearchWindow(kind, self)
        window.chart_requested.connect(lambda code, k=kind: self._open_chart(code, SPECS[k].title))
        self._daily_research_windows.append(window)
        window.destroyed.connect(lambda _=None, w=window: self._daily_research_windows.remove(w) if w in self._daily_research_windows else None)
        window.show(); window.raise_()

    def _open_research_archive(self) -> None:
        window = ResearchArchiveWindow(self); window.stock_requested.connect(lambda code: self._open_chart(code, "연구자료"))
        self._research_windows.append(window)
        window.destroyed.connect(lambda _=None, w=window: self._research_windows.remove(w) if w in self._research_windows else None)
        window.show(); window.raise_()

    def _ask_assistant(self) -> None:
        prompt = self.ai_prompt.toPlainText().strip()
        if not prompt: return
        checked = self._checked_period()
        if checked is None: return
        period = (checked.start, checked.end)
        self._assistant.set_screen_rank_limit(self.rank_limit.value())
        self.ai_prompt.clear(); self._append_ai("사용자", prompt); self.ai_send.setEnabled(False)
        self.status.setText("Codex가 DB·연구자료·Stock 파일을 확인 중입니다...")
        self._tasks.submit(lambda: self._assistant.ask(prompt, period=period), on_result=self._assistant_ready,
                           on_error=lambda trace: self._assistant_failed(trace),
                           on_finished=lambda: self.ai_send.setEnabled(True), channel="assistant")

    def _assistant_ready(self, reply) -> None:
        self._append_ai("AI", reply.text, reply.citations)
        if not reply.frame.empty: self._show_ai_frame(reply.frame, reply.labels, reply.heading)
        if reply.chart_ticker: self._open_chart(reply.chart_ticker, "AI 분석 결과")
        self.status.setText("AI 분석 완료")

    def _assistant_failed(self, trace: str) -> None:
        message = user_friendly_error(trace); self._append_ai("AI", f"작업을 완료하지 못했습니다.\n{message}")
        self.status.setText(message)

    def _append_ai(self, role: str, text: str, citations=()) -> None:
        body = escape(str(text)).replace("\n", "<br>")
        links = "".join(f'<br><a href="{escape(url)}">{escape(title)}</a>' for title, url in citations)
        self.ai_conversation.append(f"<p><b>{escape(role)}</b><br>{body}{links}</p>")

    def _clear_assistant(self) -> None:
        self._assistant.clear(); self.ai_conversation.clear(); self.status.setText("AI 대화를 지웠습니다.")

    def _open_code_library(self) -> None:
        if self._code_library_window is None:
            self._code_library_window = ReusableCodeWindow(self._assistant, self)
            self._code_library_window.destroyed.connect(lambda: setattr(self, "_code_library_window", None))
        self._code_library_window.refresh(); self._code_library_window.show(); self._code_library_window.raise_()

    def _show_ai_frame(self, frame, labels, heading: str) -> None:
        presentation = AiResultPresenter().present(frame, labels)
        self._result_ticker_column = presentation.ticker_column
        self._results = []
        self._table_navigation = self._frame_navigation(presentation, heading)
        self.result_table.clear(); self.result_table.setColumnCount(len(presentation.headers)); self.result_table.setRowCount(len(presentation.rows))
        self.result_table.setHorizontalHeaderLabels(presentation.headers)
        for column in range(len(presentation.headers)): self.result_table.horizontalHeaderItem(column).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        qt_alignments = {"center": Qt.AlignmentFlag.AlignCenter,
                         "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter}
        for row, values in enumerate(presentation.rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setTextAlignment(qt_alignments[presentation.alignments[column]])
                self.result_table.setItem(row, column, item)
        self.result_table.resizeColumnsToContents(); self.heading.setText(heading)

    @staticmethod
    def _frame_navigation(presentation, heading: str):
        items = [{"code": code, "values": row} for code, row in zip(presentation.codes, presentation.rows) if len(code) == 6]
        return {"title": heading, "headers": presentation.headers, "items": items,
                "alignments": presentation.alignments} if items else None

    def _checked_period(self) -> DateRange | None:
        try: return DateRange(self.start_date.value(), self.end_date.value())
        except ValueError as error:
            self.status.setText(str(error)); QMessageBox.warning(self, "기간 오류", str(error)); return None

    @staticmethod
    def _trace_message(error) -> str:
        text = str(error); return text.splitlines()[-1] if text else "알 수 없는 오류"

    def _show_error(self, title: str, exc) -> None:
        message = self._trace_message(exc); self.status.setText(message); QMessageBox.critical(self, title, message)

    @property
    def screening_table(self): return self.result_table
    @property
    def chart(self): return self._chart_window.chart if self._chart_window else None
    def _chart_now(self) -> None: self._open_selected_chart()
    def _clear_screening_results(self) -> None:
        self._results = []; self._table_navigation = None; self.result_table.setRowCount(0)
