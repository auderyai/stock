from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

from krx_research.qt.presentation.error_presenter import user_friendly_error
from krx_research.qt.services.ports import ErrorLogPort
from krx_research.qt.workers.task_runner import TaskRunner
from krx_research.qt.scenario_window import open_scenario_window


class ChartController(QObject):
    """Coordinates asynchronous chart loading and synchronized list navigation."""

    def __init__(self, view, chart_service, error_log: ErrorLogPort, parent=None):
        super().__init__(parent or view)
        self.view = view
        self.chart_service = chart_service
        self.runner = TaskRunner(self)
        self.error_log = error_log
        self.dataset = None
        self._loading_ticker: str | None = None
        view.reloadRequested.connect(self.load)
        view.scenarioRequested.connect(self.open_scenario)
        view.navigationTickerChanged.connect(self._navigation_selected)

    def load(self) -> None:
        ticker = str(self.view.ticker).strip()
        venue = self.view.quote_venue
        self._loading_ticker = ticker
        self.view.set_loading(f"{ticker} 차트 자료를 불러오는 중입니다...")
        self.runner.submit(
            lambda: self.chart_service.load(ticker, venue),
            on_result=lambda dataset, expected=ticker: self._ready(expected, dataset),
            on_error=self._error,
        )

    def set_ticker(self, ticker: str, quote_venue: str | None = None) -> None:
        code = str(ticker).strip()
        if not code:
            return
        if code == str(self.view.ticker).strip() and self.dataset is not None:
            return
        self.view.ticker = code
        if quote_venue:
            self.view.quote_venue = quote_venue
        self.load()

    def _navigation_selected(self, ticker: str) -> None:
        self.set_ticker(ticker, self.view.quote_venue)

    def _ready(self, expected_ticker: str, dataset) -> None:
        # Ignore an older worker result if the user moved through the list quickly.
        if str(self.view.ticker).strip() != str(expected_ticker).strip():
            return
        self.dataset = dataset
        assessments = self.chart_service.assess_strategies(dataset)
        self.view.set_dataset(dataset, assessments)

    def _error(self, trace: str) -> None:
        path = self.error_log.write(trace)
        message = user_friendly_error(trace)
        if path:
            message += f"\n\n오류 로그: {path}"
        self.view.set_loading("차트 자료를 불러오지 못했습니다.")
        QMessageBox.critical(self.view, "차트 오류", message)

    def open_scenario(self) -> None:
        if self.dataset is None or self.dataset.daily.empty:
            QMessageBox.information(self.view, "보조지표 시나리오", "선택 종목의 일봉을 먼저 불러오십시오.")
            return
        window = open_scenario_window(
            self.view,
            self.dataset.daily.copy(deep=True),
            self.dataset.ticker,
            self.dataset.market,
        )
        self.view.keep_child(window)
