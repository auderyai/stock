from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from krx_research_nextgen.application.container import ApplicationContainer
from krx_research_nextgen.models.screening import ScreeningKind


def main() -> int:
    app = QApplication.instance() or QApplication([])
    with ApplicationContainer() as container:
        container.window.show()
        app.processEvents()
        if not container.window.isVisible():
            raise RuntimeError("NextGen main window is not visible")
        status_deadline = time.monotonic() + 30
        while not container.window.end_date.isEnabled() and time.monotonic() < status_deadline:
            app.processEvents(); time.sleep(.01)
        if not container.window.end_date.isEnabled():
            raise RuntimeError("Database trade dates were not loaded")
        container.window.start_date.setDate(container.window.end_date.date())
        container.window._run_screening(ScreeningKind.HIGH_52W, 50, "ALL")
        screen_deadline = time.monotonic() + 30
        while not container.window.run_button.isEnabled() and time.monotonic() < screen_deadline:
            app.processEvents(); time.sleep(.01)
        rows = container.window.screening_table.rowCount()
        if rows < 1:
            raise RuntimeError("52-week-high results were not rendered")
        container.window._chart_now()
        selected = container.window._current_code
        chart_deadline = time.monotonic() + 30
        chart = container.window.chart
        while (chart is None or any(len(axis.vb.addedItems) < 1 for axis in chart.axs)) \
                and time.monotonic() < chart_deadline:
            app.processEvents(); time.sleep(.01); chart = container.window.chart
        if chart is None:
            raise RuntimeError("Legacy-compatible chart window was not opened")
        item_counts = [len(axis.vb.addedItems) for axis in chart.axs]
        app.processEvents()
        left_edges = [round(axis.vb.sceneBoundingRect().left(), 1) for axis in chart.axs if axis.ax_widget.isVisible()]
        if not selected or any(count < 1 for count in item_counts):
            raise RuntimeError("Selected 52-week-high chart was not rendered")
        if max(left_edges) - min(left_edges) > 0.5:
            raise RuntimeError(f"Chart panels are not horizontally aligned: {left_edges}")
        chart_window = container.window._chart_window
        if len(chart_window._bundle.assessments) != 3 or "제시 리버모어" not in chart_window.strategy_text.toPlainText():
            raise RuntimeError("Classic-strategy assessments were not rendered")
        chart_window.strategy_mode.setCurrentText("제시 리버모어"); app.processEvents()
        if "제시 리버모어" not in chart_window.chart.strategy_overlay.text():
            raise RuntimeError("Selected classic-strategy overlay was not rendered")
        chart_window.scenario_button.click()
        app.processEvents()
        if not container.window._scenario_windows or not container.window._scenario_windows[-1].isVisible():
            raise RuntimeError("Indicator scenario window did not open")
        scenario = container.window._scenario_windows[-1]
        scenario.horizon.setText("5"); scenario.run_button.click()
        deadline = time.monotonic() + 30
        while not scenario.run_button.isEnabled() and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.01)
        analysis = scenario._analysis
        if (analysis is None or not analysis.checkpoints or analysis.path.empty or
                scenario.table.rowCount() != len(analysis.checkpoints) or
                len(scenario.price_plot.listDataItems()) < 3 or not scenario.indicator_plot.listDataItems()):
            raise RuntimeError("Indicator scenario analysis returned no data")
        QTimer.singleShot(1500, app.quit)
        result = int(app.exec() or 0)
        print(
            f"NEXTGEN_RUNTIME: PASS title={container.window.windowTitle()!r} "
            f"high_52w_rows={rows} selected={selected} "
            f"chart_items={item_counts} left_edges={left_edges} scenario_rows={len(analysis.checkpoints)} exit={result}"
        )
        return result


if __name__ == "__main__":
    raise SystemExit(main())
