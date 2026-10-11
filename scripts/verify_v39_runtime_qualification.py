from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.application.xing_runtime import XingRuntimeQualificationService


class FakeBridge:
    def __init__(self) -> None:
        self.connected = False
        self.calls: list[tuple[str, dict[str, str]]] = []

    def connect(self) -> None:
        self.connected = True

    def raw_tr(self, tr: str, values: dict[str, str]):
        assert self.connected
        self.calls.append((tr, values))
        fixtures = {
            "t8424": {"rows": [{"upcode": "001", "hname": "코스피200"}], "header": {}},
            "t8436": {"rows": [{"shcode": "005930", "hname": "삼성전자"}], "header": {}},
            "t8429": {"rows": [{"date": "20261002", "close": 70000}], "header": {}},
            "t8451": {"rows": [{"date": "20261002", "close": 70000}], "header": {}},
            "t1516": {"rows": [{"shcode": "005930"}], "header": {}},
            "t1702": {"rows": [{"date": "20261002", "tjj0000_vol": 1}], "header": {}},
        }
        return fixtures[tr]


def main() -> int:
    bridge = FakeBridge()
    service = XingRuntimeQualificationService(bridge, today=dt.date(2026, 10, 5))
    report = service.qualify()
    assert report.passed, report
    assert report.stock_code == "005930"
    assert report.sector_code == "001"
    assert [tr for tr, _ in bridge.calls] == list(service.REQUIRED_TRS)
    t8451_values = dict(bridge.calls)["t8451"]
    assert t8451_values["exchgubun"] == "K"
    t1702_values = dict(bridge.calls)["t1702"]
    assert t1702_values["shcode"] == "005930"
    print("V39_RUNTIME_QUALIFICATION_UNIT_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
