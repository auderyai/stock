from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(r"C:\stock")
NEXTGEN_SRC = ROOT / "nextgen" / "src"
if str(NEXTGEN_SRC) not in sys.path:
    sys.path.insert(0, str(NEXTGEN_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton, QSpinBox

from krx_research_nextgen.models.screening import ScreeningKind
from krx_research_nextgen.widgets.screening_panel import ScreeningPanel


def main() -> int:
    app = QApplication.instance() or QApplication([])

    panel = ScreeningPanel()
    panel.show()
    app.processEvents()

    kind_combo = panel.findChild(QComboBox, "screeningKindCombo")
    universe_combo = panel.findChild(QComboBox, "screeningUniverseCombo")
    topn_spin = panel.findChild(QSpinBox, "screeningTopNSpin")
    run_button = panel.findChild(QPushButton, "screeningRunButton")

    assert kind_combo is not None
    assert universe_combo is not None
    assert topn_spin is not None
    assert run_button is not None

    expected_universes = {
        "ALL", "KOSPI", "KOSDAQ", "KONEX", "KOSPI200", "KOSDAQ150"
    }
    actual_universes = {
        str(universe_combo.itemData(i)) for i in range(universe_combo.count())
    }
    assert actual_universes == expected_universes, actual_universes
    assert topn_spin.minimum() == 1
    assert topn_spin.maximum() == 500
    assert topn_spin.value() == 50

    reset_count = 0
    run_events = []

    def on_reset():
        nonlocal reset_count
        reset_count += 1

    panel.reset_requested.connect(on_reset)
    panel.run_requested.connect(
        lambda kind, limit, universe:
        run_events.append((kind, int(limit), str(universe)))
    )

    # Criteria changes must invalidate stale results.
    kospi200_index = next(
        i for i in range(universe_combo.count())
        if str(universe_combo.itemData(i)) == "KOSPI200"
    )
    universe_combo.setCurrentIndex(kospi200_index)
    topn_spin.setValue(100)
    app.processEvents()

    assert reset_count >= 2, reset_count

    # Run signal must carry final universe/TOP-N.
    run_button.click()
    app.processEvents()

    assert len(run_events) == 1
    kind, limit, universe = run_events[0]
    assert isinstance(kind, ScreeningKind)
    assert limit == 100
    assert universe == "KOSPI200"

    # Every screener kind must be selectable.
    assert kind_combo.count() == len(list(ScreeningKind))

    panel.close()
    app.processEvents()

    print("GUI_PANEL_UNIVERSES:", sorted(actual_universes))
    print("GUI_PANEL_TOPN_RANGE:", topn_spin.minimum(), topn_spin.maximum())
    print("GUI_PANEL_RESET_EVENTS:", reset_count)
    print("GUI_PANEL_RUN_EVENT:", run_events[0])
    print("STAGE4_GUI_PANEL_VERIFY: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
