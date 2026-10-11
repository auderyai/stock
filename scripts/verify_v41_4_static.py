from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("NEW_STOCK_ROOT", Path(__file__).resolve().parents[1]))
SERVICE = ROOT / "src/krx_research/application/xing_db/service.py"
RATE = ROOT / "src/krx_research/infrastructure/xing_db/rate_limited_bridge.py"
errors: list[str] = []

for p in (SERVICE, RATE):
    if not p.is_file():
        errors.append(f"missing: {p}")

if not errors:
    service = SERVICE.read_text(encoding="utf-8")
    rate = RATE.read_text(encoding="utf-8")
    required_service = (
        '"t8429"',
        '"qrycnt": "200"',
        't8429_request_start = self._expanded_request_start(effective_as_of, effective_as_of)',
        'self._filter_rows_by_date(raw_rows, effective_as_of, effective_as_of)',
        't8429 업종 조회 실패: upcode=',
    )
    for token in required_service:
        if token not in service:
            errors.append(f"service missing: {token}")
    if '"qrycnt": "20"' in service[service.find('t8429_request_start'):service.find('stages.append(StageResult("t8429')]:
        errors.append("legacy t8429 qrycnt=20 remains in Menu 2 block")
    if '"t8429": 1.10' not in rate:
        errors.append("t8429 pacing must be 1.10s")
    if '"t1516": 1.10' not in rate or '"t1702": 1.10' not in rate:
        errors.append("previous qualified rate limits changed unexpectedly")
    if "time.sleep" in service or "import time" in service:
        errors.append("application service must not contain transport sleep")

if errors:
    print("V41_4_STATIC_CHECK: FAIL")
    for e in errors:
        print("FAIL:", e)
    raise SystemExit(1)
print("V41_4_STATIC_CHECK: PASS")
