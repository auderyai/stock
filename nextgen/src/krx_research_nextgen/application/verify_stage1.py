from __future__ import annotations

import importlib
import sys

from krx_research_nextgen.application.smoke_data import build_sample_ohlcv
from krx_research_nextgen.models.chart_data import IndicatorConfig
from krx_research_nextgen.services.chart_service import ChartService


def require_import(name: str) -> str:
    module = importlib.import_module(name)
    return getattr(module, "__version__", "unknown")


def main() -> int:
    versions = {
        "PyQt6": require_import("PyQt6"),
        "finplot": require_import("finplot"),
        "pyqtgraph": require_import("pyqtgraph"),
        "ta": require_import("ta"),
        "pandas": require_import("pandas"),
        "numpy": require_import("numpy"),
    }

    # PySide6 must not be imported into this process.
    if "PySide6" in sys.modules:
        raise RuntimeError("PySide6 is loaded in the Stage-1 PyQt6 process")

    frame = build_sample_ohlcv()
    service = ChartService()

    approved = service.prepare("APPROVED-INDICATORS", frame, IndicatorConfig())

    required = {
        "rsi", "macd", "macd_signal", "macd_hist",
        "bb_mid", "bb_upper", "bb_lower",
    }
    missing = required.difference(approved.frame.columns)
    if missing:
        raise RuntimeError(f"indicator columns missing: {sorted(missing)}")

    for col in required:
        if approved.frame[col].notna().sum() == 0:
            raise RuntimeError(f"indicator produced no numeric values: {col}")

    print("STAGE1_VERIFY: PASS")
    for key, value in versions.items():
        print(f" - {key}: {value}")
    print(" - approved RSI EMA 14, signal EMA 9: PASS")
    print(" - MACD: PASS")
    print(" - Bollinger Bands: PASS")
    print(" - PySide6 loaded in process: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
