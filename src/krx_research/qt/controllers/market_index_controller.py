from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

from krx_research.qt.scenario_window import open_scenario_window
from krx_research.qt.workers.task_runner import TaskRunner


class MarketIndexController(QObject):
    """Orchestrates index navigation; View stays SQL-free and logic stays in Service."""

    def __init__(self, view, service, parent=None):
        super().__init__(parent or view)
        self.view = view
        self.service = service
        self.runner = TaskRunner(self)
        self._entries: dict[str, dict] = {}
        self._requested_code: str | None = None
        self._dataset = None
        self._children = []
        view.indexRequested.connect(self.load_code)
        view.strategyRefreshRequested.connect(self.refresh_strategy)
        view.scenarioRequested.connect(self.open_scenario)

    def initialize(self) -> None:
        self.view.set_status("지수 목록을 불러오는 중입니다...")
        self.runner.submit(self.service.list_overview, on_result=self._overview_ready, on_error=self._error)

    def _overview_ready(self, result) -> None:
        entries, overview = result
        self._entries = {str(item["index_code"]): item for item in entries}
        self.view.set_entries(entries, overview)
        if not entries:
            self.view.set_status("지수 데이터가 없습니다. 지수 갱신을 실행하세요.")

    def load_code(self, code: str) -> None:
        code = str(code)
        item = self._entries.get(code)
        if item is None:
            return
        self._requested_code = code
        self.view.set_status("지수 차트를 불러오는 중입니다...")
        self.runner.submit(
            lambda: self.service.load_dataset(item),
            on_result=lambda dataset, requested=code: self._dataset_ready(requested, dataset),
            on_error=self._error,
        )

    def _dataset_ready(self, code: str, dataset) -> None:
        if code != self._requested_code:
            return
        self._dataset = dataset
        assessments = self.service.assess_strategies(dataset, self.view.controls.days_value())
        self.view.set_dataset(dataset, assessments)

    def refresh_strategy(self, dataset, days) -> None:
        if dataset is None:
            return
        self.view.set_strategy_assessments(self.service.assess_strategies(dataset, days))

    def open_scenario(self) -> None:
        if self._dataset is None or self._dataset.daily.empty:
            QMessageBox.information(self.view, "보조지표 시나리오", "지수 일봉을 먼저 불러오십시오.")
            return
        window = open_scenario_window(
            self.view, self._dataset.daily.copy(deep=True), self._dataset.ticker, self._dataset.market
        )
        self._children.append(window)
        window.destroyed.connect(lambda _=None, w=window: self._children.remove(w) if w in self._children else None)

    def _error(self, trace: str) -> None:
        self.view.set_status("지수 자료를 불러오지 못했습니다.")
        QMessageBox.critical(self.view, "지수 오류", trace.splitlines()[-1] if trace else "알 수 없는 오류")
