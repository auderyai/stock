from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.application.xing_db.e2e_models import Menu2Snapshot, WriteCandidate
from krx_research.application.xing_db.e2e_service import DbMenuE2EVerificationService

DAY = dt.date(2026, 10, 2)


class FakeProbe:
    def __init__(self) -> None:
        self.combined = 0
        self.raw = 0
        self.cp = 0
        self.menu2_runs = 0

    def latest_market_date(self): return DAY
    def find_combined_gap(self, start, end): return WriteCandidate("005930", DAY, "test gap")
    def combined_row_count(self, stock_code, trade_date): return self.combined
    def find_investor_gap(self, start, end): return WriteCandidate("000660", DAY, "test gap")
    def investor_matrix_count(self, stock_code, trade_date): return self.raw
    def investor_checkpoint_count(self, stock_code, trade_date): return self.cp
    def menu2_snapshot(self, as_of):
        if self.menu2_runs == 0:
            return Menu2Snapshot(as_of, 252, 4306, 0, 0, 0, 0, 0, 0, 0)
        return Menu2Snapshot(as_of, 252, 4306, 200, 150, 252, 0, 0, 0, 0)
    def close(self): pass


class FakeCommands:
    def __init__(self, probe): self.p = probe
    def run_menu7_single_combined(self, stock_code, trade_date): self.p.combined = 1; return 0
    def run_menu5_single_day(self, stock_code, trade_date): self.p.raw = 4; self.p.cp = 1; return 0
    def run_menu2_full(self, as_of): self.p.menu2_runs += 1; return 0


def main() -> int:
    probe = FakeProbe()
    results = DbMenuE2EVerificationService(probe, FakeCommands(probe)).run_all(lookback_days=30)
    if len(results) != 3 or not all(r.passed for r in results):
        for r in results: print(r)
        return 1
    print("V41_E2E_UNIT_CHECK: PASS")
    return 0


if __name__ == "__main__": raise SystemExit(main())
