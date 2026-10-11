from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox, QWidget

from krx_research.qt.chart_window import ChartWindow
from krx_research.qt.models.date_range import DateRange
from krx_research.qt.strategies.chart_navigation import (
    NewChartWindowStrategy,
    SynchronizedChartStrategy,
)
from krx_research.qt.workers.task_runner import TaskRunner


class InvestorDashboardController(QObject):
    """Investor-flow orchestration only; SQL and rendering stay outside."""

    def __init__(self, view, service, chart_service, *, navigate: bool = False, parent=None):
        super().__init__(parent or view)
        self.view = view
        self.service = service
        self.chart_service = chart_service
        self.navigate = bool(navigate)
        self.runner = TaskRunner(self)
        self._charts: list[QWidget] = []
        self._new_chart = NewChartWindowStrategy(self._create_chart_window, self._keep_window)
        self._sync_chart = SynchronizedChartStrategy(self._create_chart_window, self._keep_window)
        view.queryRequested.connect(self.reload)
        view.chartRequested.connect(self.open_chart)

    def initialize(self) -> None:
        self.view.initialize()

    def reload(self, start, end, top_n: int) -> None:
        try:
            period = DateRange(start, end).validate()
        except ValueError as exc:
            QMessageBox.warning(self.view, "조회 기간", str(exc))
            return
        self.view.set_status("수급 DB 조회 중...")
        self.runner.submit(
            lambda: self.service.load(period.start, period.end, top_n=top_n),
            on_result=self.view.render,
            on_error=self._error,
        )

    def open_chart(self, ticker: str, frame, labels) -> None:
        strategy = self._sync_chart if self.navigate else self._new_chart
        strategy.open(
            ticker=ticker,
            quote_venue="KRX",
            frame=frame,
            labels=labels,
            parent=self.view,
        )

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

    def _keep_window(self, window: QWidget):
        if window not in self._charts:
            self._charts.append(window)
            window.destroyed.connect(
                lambda _=None, w=window: self._charts.remove(w) if w in self._charts else None
            )
        window.show()
        return window

    def _error(self, trace: str) -> None:
        self.view.set_status("수급 자료를 불러오지 못했습니다.")
        QMessageBox.critical(
            self.view,
            "수급 오류",
            trace.splitlines()[-1] if trace else "알 수 없는 오류",
        )
