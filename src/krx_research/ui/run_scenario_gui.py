"""Compatibility entry point for the PySide6 indicator-scenario window."""
from __future__ import annotations

import pandas as pd

from krx_research.qt.scenario_window import ScenarioWindow, open_scenario_window


def main() -> int:
    import sys
    from PySide6.QtWidgets import QApplication, QFileDialog

    app = QApplication.instance() or QApplication(sys.argv)
    filename, _ = QFileDialog.getOpenFileName(None, "선택 종목의 일봉 CSV", "", "CSV (*.csv)")
    if not filename:
        return 0
    data = pd.read_csv(filename, encoding="utf-8-sig")
    window = ScenarioWindow(data, filename.rsplit("/", 1)[-1])
    window.show()
    return int(app.exec() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
