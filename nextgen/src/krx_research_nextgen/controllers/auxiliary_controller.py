from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from krx_research_nextgen.windows.auxiliary_windows import InvestorDashboardWindow, MarketIndexWindow
from krx_research_nextgen.workers.task_runner import TaskRunner


class AuxiliaryController(QObject):
    """Owns auxiliary views and keeps PostgreSQL work outside the GUI thread."""

    def __init__(self, service, parent=None) -> None:
        super().__init__(parent); self._service, self._runner, self._windows = service, TaskRunner(self), []

    def _keep(self, window):
        self._windows.append(window); window.destroyed.connect(lambda _=None,w=window: self._windows.remove(w) if w in self._windows else None)
        window.show(); window.raise_(); return window

    def open_investor(self, parent, start, end) -> None:
        view = self._keep(InvestorDashboardWindow(parent))
        view.stock_requested.connect(self.stock_requested.emit)
        self._runner.submit(lambda: self._service.investor_dashboard(start, end),
                            on_result=lambda data: view.render(data, start, end), on_error=lambda trace: view.show_error(trace.splitlines()[-1]), channel=f"investor:{id(view)}")

    def open_market_index(self, parent) -> None:
        view = self._keep(MarketIndexWindow(parent)); entries = {}
        def ready(rows):
            entries.update({str(row["index_code"]): row for row in rows}); view.render_entries(rows)
        def load(code):
            item = entries.get(code)
            if item:
                view.status.setText("지수 차트를 불러오는 중입니다...")
                self._runner.submit(lambda: self._service.index_chart(item), on_result=view.show_bundle,
                                    on_error=lambda trace: view.show_error(trace.splitlines()[-1]), channel=f"index:{id(view)}")
        view.index_requested.connect(load)
        self._runner.submit(self._service.index_entries, on_result=ready,
                            on_error=lambda trace: view.show_error(trace.splitlines()[-1]), channel=f"index-list:{id(view)}")

    stock_requested = pyqtSignal(str, object)
