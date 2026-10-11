from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main()->int:
    errors=[]
    svc=(ROOT/"src/krx_research/application/xing_db/service.py").read_text(encoding="utf-8")
    repo=(ROOT/"src/krx_research/infrastructure/xing_db/postgresql_repository.py").read_text(encoding="utf-8")
    e2e=(ROOT/"src/krx_research/application/xing_db/e2e_service.py").read_text(encoding="utf-8")
    for token in ("_LS_QUALIFIED_LOOKBACK_DAYS = 45","_expanded_request_start","_filter_rows_by_date","request_start = self._expanded_request_start"):
        if token not in svc: errors.append(f"missing service invariant: {token}")
    if "days=28" in svc: errors.append("old 29-day t1702 request window remains")
    for token in ("def _json_dumps","def _json_safe","replace(\"\\x00\", \"\")"):
        if token not in repo: errors.append(f"missing JSON NUL invariant: {token}")
    if "json.dumps(row, ensure_ascii=False)" in repo: errors.append("unsanitized row json.dumps remains")
    if "candidate = self._probe.find_completed_investor(start, end)" not in e2e:
        errors.append("menu5 non-destructive force-refresh preference missing")
    if errors:
        for e in errors: print("FAIL:",e)
        return 1
    print("V41_2_STATIC_CHECK: PASS")
    return 0
if __name__=="__main__": raise SystemExit(main())
