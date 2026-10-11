from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
service=(ROOT/'src/krx_research/application/xing_db/service.py').read_text(encoding='utf-8')
bridge=(ROOT/'src/krx_research/infrastructure/xing_db/rate_limited_bridge.py').read_text(encoding='utf-8')
ports=(ROOT/'src/krx_research/application/xing_db/ports.py').read_text(encoding='utf-8')
repo=(ROOT/'src/krx_research/infrastructure/xing_db/postgresql_repository.py').read_text(encoding='utf-8')
checks={
 'resume':'completed_sector_codes' in service and 'pending_targets' in service and 't8429 RESUME' in service,
 'port':'completed_sector_codes' in ports,
 'repo':'def completed_sector_codes' in repo and 'ls_sector_ohlcv_daily' in repo,
 '1sec':'"t8429": 1.10' in bridge,
 '200per10m':'"t8429": (200, 600.0)' in bridge,
 'quota_wait':'_countdown_sleep' in bridge and 'XING QUOTA' in bridge,
}
fail=[k for k,v in checks.items() if not v]
if fail: raise SystemExit('V41_7_QUOTA_RESUME_STATIC: FAIL '+','.join(fail))
print('V41_7_QUOTA_RESUME_STATIC: PASS')
