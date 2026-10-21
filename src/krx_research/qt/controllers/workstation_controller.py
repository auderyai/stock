from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from krx_research.qt.chart_window import ChartWindow
from krx_research.qt.models.window_state import WorkstationState
from krx_research.qt.models.date_range import DateRange
from krx_research.qt.presentation.error_presenter import user_friendly_error
from krx_research.qt.presentation.screen_presenter import ScreenResultPresenter
from krx_research.qt.services.chart_service import ChartService
from krx_research.qt.services.ports import ErrorLogPort
from krx_research.qt.services.export_service import ExcelExportService
from krx_research.qt.services.screening_service import ScreeningService
from krx_research.qt.services.security_search_service import SecuritySearchService
from krx_research.qt.services.assistant_service import AssistantService
from krx_research.qt.strategies.chart_navigation import NewChartWindowStrategy, SynchronizedChartStrategy
from krx_research.qt.workers.task_runner import TaskRunner
from krx_research.qt.windows.reusable_code_window import ReusableCodeWindow


class WorkstationController(QObject):
    """Application controller: event orchestration only; no SQL and no rendering."""

    def __init__(
        self,
        view,
        screening: ScreeningService,
        chart_service: ChartService,
        exporter: ExcelExportService,
        security_search: SecuritySearchService,
        window_factory,
        assistant: AssistantService,
        error_log: ErrorLogPort,
        parent=None,
    ):
        super().__init__(parent or view)
        self.view = view
        self.screening = screening
        self.chart_service = chart_service
        self.exporter = exporter
        self.security_search = security_search
        self.window_factory = window_factory
        self.assistant = assistant
        self.presenter = ScreenResultPresenter()
        self.error_log = error_log
        self.state = WorkstationState()
        self.runner = TaskRunner(self)
        self._display_frame = None
        self._display_labels: dict[str, str] = {}
        self._new_chart_strategy = NewChartWindowStrategy(self._create_chart_window, self._keep_window)
        self._sync_chart_strategy = SynchronizedChartStrategy(self._create_chart_window, self._keep_window)

        view.runRequested.connect(self.run_screen)
        view.exportRequested.connect(self.export_results)
        view.chartRequested.connect(self.open_selected_chart)
        view.investorRequested.connect(self.open_investor)
        view.marketIndexRequested.connect(self.open_market_index)
        view.featuredRequested.connect(self.open_featured)
        view.themeRequested.connect(self.open_theme)
        view.researchArchiveRequested.connect(self.open_research_archive)
        view.synchronizedChartRequested.connect(self.update_synchronized_chart)
        view.securitySearchRequested.connect(self.search_security)
        view.directChartRequested.connect(self.open_direct_chart)
        view.comparisonTickerRequested.connect(self.set_comparison_ticker)
        view.near52wRequested.connect(self.run_near_52w)
        view.assistantRequested.connect(self.ask_assistant)
        view.assistantClearRequested.connect(self.clear_assistant)
        view.assistantCodeLibraryRequested.connect(self.open_code_library)

    def initialize(self) -> None:
        today = dt.date.today()
        venue = self.view.query_panel.quote_venue()
        try:
            dates = self.screening.available_dates(quote_venue=venue)
            current = max(dates) if dates else today
        except Exception as exc:
            current = today
            self.view.set_status(f"데이터베이스 기준일 확인 실패: {exc}")
        self.view.query_panel.set_dates(current)

    def run_screen(self) -> None:
        key = self.view.screen_selector.selected_key()
        if not key:
            QMessageBox.information(self.view, "조회", "스크리닝 항목을 선택하십시오.")
            return
        self._run_screen_key(key)

    def run_near_52w(self) -> None:
        self._run_screen_key("near_high_52w")

    def _run_screen_key(self, key: str) -> None:
        comparison = self.view.comparison_ticker() if key == "ema_similarity" else None
        if key == "ema_similarity" and not comparison:
            QMessageBox.information(
                self.view,
                "이동평균 유사배열",
                "왼쪽의 '종목 검색'에서 기준 종목을 먼저 찾고\n'유사배열 기준종목으로 사용'을 누르십시오.",
            )
            return
        try:
            query = self.view.query_panel.build_query(key, comparison_ticker=comparison)
            query.validate()
        except Exception as exc:
            QMessageBox.warning(self.view, "조회 조건", str(exc))
            return
        self.state.busy = True
        self.view.set_busy(True)
        self.runner.submit(
            lambda: self.screening.execute(query),
            on_result=self._screen_ready,
            on_error=self._error,
            on_finished=self._finished,
        )

    def _screen_ready(self, dataset) -> None:
        self.state.current_dataset = dataset
        presented = self.presenter.present(dataset)
        self._display_frame = presented.frame
        self._display_labels = presented.labels
        freshness = self.screening.freshness(dataset)
        status = f"{len(presented.frame):,}개 종목"
        if freshness:
            status += f" · {freshness}"
        self.view.show_dataset(presented.frame, presented.labels, presented.heading, status)

    def _error(self, trace: str) -> None:
        log_path = self.error_log.write(trace)
        message = user_friendly_error(trace)
        if log_path:
            message += f"\n\n오류 로그: {log_path}"
        self.view.set_status("작업 중 오류가 발생했습니다.")
        QMessageBox.critical(self.view, "실행 오류", message)

    def _finished(self) -> None:
        self.state.busy = False
        self.view.set_busy(False)

    def export_results(self) -> None:
        frame = self._display_frame
        if frame is None or frame.empty:
            QMessageBox.information(self.view, "Excel", "저장할 결과가 없습니다.")
            return
        path, _ = QFileDialog.getSaveFileName(self.view, "Excel 저장", "screen_result.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        try:
            export_frame = frame.rename(columns=self._display_labels)
            target = self.exporter.export(export_frame, path)
            self.view.set_status(f"저장 완료: {target}")
        except Exception as exc:
            QMessageBox.critical(self.view, "Excel 오류", str(exc))

    def search_security(self, query: str) -> None:
        text = str(query).strip()
        if not text:
            return
        self.view.set_status(f"'{text}' 종목을 찾는 중입니다...")
        self.runner.submit(
            lambda: self.security_search.search(text, limit=30),
            on_result=self._search_ready,
            on_error=self._error,
        )

    def _search_ready(self, rows: list[dict[str, str]]) -> None:
        self.view.set_search_results(rows)
        if not rows:
            QMessageBox.information(self.view, "종목 검색", "일치하는 종목을 찾지 못했습니다.")

    def set_comparison_ticker(self, ticker_or_name: str) -> None:
        try:
            code = self.security_search.resolve(ticker_or_name)
            rows = self.security_search.search(code, limit=1)
            name = rows[0].get("name", "") if rows else ""
            self.view.set_comparison_ticker(code, name)
        except Exception as exc:
            QMessageBox.warning(self.view, "기준 종목", str(exc))

    def _keep_window(self, window: QWidget):
        if window not in self.state.child_windows:
            self.state.child_windows.append(window)
            window.destroyed.connect(
                lambda _=None, w=window: self.state.child_windows.remove(w)
                if w in self.state.child_windows else None
            )
        window.show()
        return window

    def _create_chart_window(
        self,
        *,
        ticker: str,
        quote_venue: str,
        parent,
        navigation_enabled: bool,
        navigation_frame=None,
        navigation_labels=None,
    ):
        return ChartWindow(
            self.chart_service,
            ticker,
            quote_venue=quote_venue,
            parent=parent,
            navigation_enabled=navigation_enabled,
            navigation_frame=navigation_frame,
            navigation_labels=navigation_labels or {},
        )

    def _chart_strategy(self):
        return self._sync_chart_strategy if self.view.synchronized_chart_enabled() else self._new_chart_strategy

    def open_direct_chart(self, ticker_or_name: str) -> None:
        try:
            code = self.chart_service.resolve(ticker_or_name)
            # Direct/manual search always opens only that selected stock.
            self._new_chart_strategy.open(
                ticker=code,
                quote_venue=self.view.query_panel.quote_venue(),
                frame=self._display_frame if self._display_frame is not None else self.view.result_table.frame,
                labels=self._display_labels,
                parent=self.view,
            )
        except Exception as exc:
            QMessageBox.warning(self.view, "종목 차트", str(exc))

    def open_selected_chart(self) -> None:
        ticker = self.view.result_table.current_ticker()
        if not ticker:
            QMessageBox.information(self.view, "차트", "종목 행을 선택하십시오.")
            return
        frame = self.view.result_table.frame
        strategy = self._chart_strategy()
        strategy.open(
            ticker=ticker,
            quote_venue=self.view.query_panel.quote_venue(),
            frame=frame,
            labels=self._display_labels,
            parent=self.view,
        )

    def update_synchronized_chart(self, ticker: str) -> None:
        # Selection changes update an already-open synchronized chart only.
        # They never create a new chart implicitly.
        if not self.view.synchronized_chart_enabled():
            return
        self._sync_chart_strategy.selection_changed(ticker, self.view.query_panel.quote_venue())

    def _keep_managed_window(self, managed):
        # Retain both the view and its controller so Qt signal connections and
        # worker ownership remain alive for the lifetime of the child window.
        view = managed.view
        setattr(view, "_managed_controller", managed.controller)
        return self._keep_window(view)

    def open_investor(self) -> None:
        start, end = self.view.query_panel.selected_dates()
        try:
            period = DateRange(start, end).validate()
        except ValueError as exc:
            QMessageBox.warning(self.view, "수급 조회 기간", str(exc))
            return
        managed = self.window_factory.investor(
            self.view,
            period.start,
            period.end,
            navigate=self.view.synchronized_chart_enabled(),
        )
        self._keep_managed_window(managed)

    def open_market_index(self) -> None:
        self._keep_managed_window(
            self.window_factory.market_index(self.view, navigate=self.view.synchronized_chart_enabled())
        )

    def open_featured(self) -> None:
        self._keep_managed_window(self.window_factory.featured(self.view))

    def open_theme(self) -> None:
        self._keep_managed_window(self.window_factory.theme(self.view))

    def open_research_archive(self) -> None:
        self._keep_managed_window(self.window_factory.research_archive(self.view))

    def ask_assistant(self, prompt: str) -> None:
        try:
            period = DateRange(*self.view.query_panel.selected_dates()).validate()
        except Exception as exc:
            QMessageBox.warning(self.view, "조회 기간", str(exc))
            return
        self.view.set_assistant_busy(True)
        self.runner.submit(
            lambda: self.assistant.ask(prompt, period=(period.start, period.end)),
            on_result=self._assistant_ready,
            on_error=self._assistant_error,
            on_finished=lambda: self.view.set_assistant_busy(False),
        )

    def _assistant_ready(self, reply) -> None:
        self.view.show_assistant_reply(reply.text, reply.citations)
        if not reply.frame.empty:
            self._display_frame, self._display_labels = reply.frame, reply.labels
            self.view.show_dataset(
                reply.frame, reply.labels, reply.heading,
                f"AI DB 조회 결과 {len(reply.frame):,}건 · Stock DB 값",
            )
        if reply.chart_ticker:
            self.open_direct_chart(reply.chart_ticker)

    def _assistant_error(self, trace: str) -> None:
        message = user_friendly_error(trace)
        self.view.show_assistant_reply(f"작업을 완료하지 못했습니다.\n{message}")
        self.view.set_status("AI 분석 중 오류가 발생했습니다.")

    def clear_assistant(self) -> None:
        self.assistant.clear()
        self.view.clear_assistant()
        self.view.set_status("AI 대화를 지웠습니다.")

    def open_code_library(self) -> None:
        self._keep_window(ReusableCodeWindow(self.assistant, self.view))
