from __future__ import annotations
import os
from pathlib import Path
ROOT = Path(os.environ.get("NEW_STOCK_ROOT", Path(__file__).resolve().parents[1]))
SERVICE = ROOT / "src/krx_research/application/xing_db/service.py"
errors=[]
if not SERVICE.is_file():
    errors.append(f"missing: {SERVICE}")
else:
    s=SERVICE.read_text(encoding='utf-8')
    required=(
        'sector_targets: list[tuple[str, str]] = []',
        't8429 업종 일봉 시작:',
        '[t8429 {position}/{target_count}]',
        'ETA {eta_seconds // 60:02d}:{eta_seconds % 60:02d}',
        '수신 {len(raw_rows):,}건 / 기준일 {len(day_rows):,}건 /',
        't8429 업종 일봉 {sector_daily:,}건 저장 완료',
        '"qrycnt": "200"',
    )
    for token in required:
        if token not in s:
            errors.append(f"service missing: {token}")
    if 'time.sleep' in s or 'import time' in s:
        errors.append('application service must not own transport sleeping')
if errors:
    print('V41_6_PROGRESS_STATIC_CHECK: FAIL')
    for e in errors: print('FAIL:',e)
    raise SystemExit(1)
print('V41_6_PROGRESS_STATIC_CHECK: PASS')
