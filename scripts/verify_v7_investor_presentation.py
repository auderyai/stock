from __future__ import annotations

import ast
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "krx_research" / "qt"
errors: list[str] = []

required = [
    SRC / "models" / "date_range.py",
    SRC / "presentation" / "investor_presenter.py",
    SRC / "application" / "window_factory.py",
]
for path in required:
    if not path.exists():
        errors.append(f"missing: {path.relative_to(ROOT)}")

# Pure presenter test (no Qt event loop required).
try:
    from krx_research.qt.presentation.investor_presenter import InvestorFlowPresenter

    frame = pd.DataFrame(
        [
            {
                "rank": 1,
                "screen_type": "kospi_foreign_net_buy",
                "ticker": "005930",
                "name": "예시",
                "market_cap": 123456789000,
                "investor_net_value": 123450000000,
                "score": 1234.5,
            },
            {
                "rank": 2,
                "screen_type": "kospi_foreign_net_sell",
                "ticker": "000660",
                "name": "예시2",
                "market_cap": 987654321000,
                "investor_net_value": -987650000000,
                "score": -9876.5,
            },
        ]
    )
    presented = InvestorFlowPresenter().present(frame)
    if "screen_type" in presented.frame.columns:
        errors.append("screen_type leaked into investor UI")
    if "score" in presented.frame.columns:
        errors.append("score leaked into investor UI")
    if list(presented.frame["flow_direction"]) != ["순매수", "순매도"]:
        errors.append("flow direction mapping is incorrect")
    if presented.labels.get("market_cap") != "시가총액(억원)":
        errors.append("market_cap Korean label is incorrect")
    if presented.labels.get("investor_net_value") != "순매매대금(억원)":
        errors.append("investor_net_value Korean label is incorrect")
except Exception as exc:
    errors.append(f"presenter test failed: {exc}")

# Static checks for the shared formatter and date-range gateway.
policy = (SRC / "presentation" / "table_policy.py").read_text(encoding="utf-8")
for token in ("investor_net_value", "100_000_000.0", ":,.1f"):
    if token not in policy:
        errors.append(f"investor net formatter missing token: {token}")

controller = (SRC / "controllers" / "workstation_controller.py").read_text(encoding="utf-8")
for token in ("DateRange(start, end).validate()", "window_factory.investor"):
    if token not in controller:
        errors.append(f"initial investor date validation missing: {token}")
for forbidden in (
    "from krx_research.ui.investor_dashboard import",
    "from krx_research.ui.market_index_window import",
    "from krx_research.featured_research.gui import",
    "from krx_research.theme_research.gui import",
):
    if forbidden in controller:
        errors.append(f"legacy GUI dependency remains: {forbidden}")

presenter = (SRC / "presentation" / "screen_presenter.py").read_text(encoding="utf-8")
if 'screen_type == "high_52w"' not in presenter:
    errors.append("52-week-high heading does not suppress redundant 기준일")

print("V7_INVESTOR_PRESENTATION_CHECK:", "PASS" if not errors else "FAIL")
for error in errors:
    print(" -", error)
sys.exit(1 if errors else 0)
