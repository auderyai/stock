from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.application.xing_db.e2e_service import DbMenuE2EVerificationService
from krx_research.infrastructure.xing_db.e2e_command_runner import LocalMenuCommandRunner
from krx_research.infrastructure.xing_db.e2e_probe_repository import PostgreSQLE2EProbeRepository


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="V41 menu 2/5/7 실제 PostgreSQL E2E 검증")
    p.add_argument("--lookback-days", type=int, default=550)
    args = p.parse_args(argv)

    probe = PostgreSQLE2EProbeRepository()
    service = DbMenuE2EVerificationService(probe, LocalMenuCommandRunner(ROOT))
    try:
        results = service.run_all(lookback_days=args.lookback_days, progress=lambda m: print(m, flush=True))
    finally:
        service.close()

    print("\n===== V41 E2E RESULT =====", flush=True)
    for result in results:
        print(f"[{'PASS' if result.passed else 'FAIL'}] {result.name}: {result.detail}", flush=True)
    passed = bool(results) and all(r.passed for r in results)
    print(f"V41 DB/MENU INTEGRATION: {'COMPLETE' if passed else 'INCOMPLETE'}", flush=True)
    return 0 if passed else 5


if __name__ == "__main__":
    raise SystemExit(main())
