from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing.bridge import XingBridgeClient
from krx_research.collectors.xing.worker_runtime import Xing32Environment


def main() -> int:
    status = Xing32Environment(ROOT).inspect()
    print(f"[1/4] 32bit worker: {'PASS' if status.available else 'FAIL'}", flush=True)
    if not status.available:
        print(status.detail, flush=True)
        return 2

    with XingBridgeClient(ROOT, delay=.08, timeout=30) as bridge:
        health = bridge.health()
        print(f"[2/4] xingAPI login/session: PASS ({health.get('worker_bits')}bit)", flush=True)

        sectors = bridge.raw_tr("t8424", {"gubun1": "0"}).get("rows", [])
        if not sectors:
            sectors = bridge.raw_tr("t8424", {"gubun1": ""}).get("rows", [])
        if not sectors:
            raise RuntimeError("t8424 응답이 비어 있습니다.")
        print(f"[3/4] t8424 업종/지수 조회: PASS ({len(sectors):,}건)", flush=True)

        master = bridge.raw_tr("t8436", {"gubun": "0"}).get("rows", [])
        if not master:
            raise RuntimeError("t8436 종목마스터 응답이 비어 있습니다.")
        print(f"[4/4] t8436 종목마스터 조회: PASS ({len(master):,}건)", flush=True)

    print("XING32_CONNECTION_SMOKE_CHECK: PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
