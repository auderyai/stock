from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.infrastructure.xing_db.adaptive_raw_bridge import AdaptiveRawTrBridge


class Response:
    def __init__(self, payload, status=200): self.payload, self.status_code, self.headers = payload, status, {}
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(self.status_code)
    def json(self): return self.payload


class Session:
    def __init__(self): self.calls, self.chart_calls = [], 0
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/oauth2/token"): return Response({"access_token": "test"})
        if url.endswith("/stock/chart"):
            self.chart_calls += 1
            cursor = "20250101" if self.chart_calls == 1 else ""
            return Response({"rsp_cd": "00000", "t8451OutBlock1": [{"date": f"2026100{self.chart_calls}"}], "t8451OutBlock": {"cts_date": cursor}})
        return Response({"rsp_cd": "00000", "t1702OutBlock1": [{"date": "20261007"}]})
    def close(self): pass


class Fallback:
    def __init__(self): self.connected = False
    def connect(self): self.connected = True
    def close(self): pass
    def raw_tr(self, tr, values): return {"rows": [{"fallback": tr}]}


class BrokenFallback(Fallback):
    def connect(self): raise RuntimeError("no xing32")


def main() -> int:
    paths = [ROOT / "src/krx_research/infrastructure/xing_db/adaptive_raw_bridge.py", ROOT / "scripts/update_ls_investor_date_range.py", ROOT / "scripts/run_xing_db_menu.py", ROOT / "src/krx_research/qt/job_menu/window.py"]
    for path in paths: ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    session = Session(); bridge = AdaptiveRawTrBridge(ROOT, session=session, credential_loader=lambda _: ("key", "secret"), sleep_fn=lambda _: None)
    bridge.connect(); primary = bridge.raw_tr("t1702", {"shcode": "005930"}); paged = bridge.raw_tr("t8451", {"shcode": "005930", "qrycnt": "2000", "cts_date": ""}); bridge.close()
    fallback = Fallback(); bridge = AdaptiveRawTrBridge(ROOT, session=Session(), credential_loader=lambda _: (_ for _ in ()).throw(RuntimeError("no key")), fallback_factory=lambda: fallback)
    bridge.connect(); delegated = bridge.raw_tr("t8424", {}); bridge.close()
    try:
        AdaptiveRawTrBridge(ROOT, session=Session(), credential_loader=lambda _: (_ for _ in ()).throw(RuntimeError("no key")), fallback_factory=BrokenFallback).connect()
        unavailable = False
    except RuntimeError as exc: unavailable = "사용 가능한 LS 데이터 공급자가 없습니다" in str(exc)
    texts = [path.read_text(encoding="utf-8-sig") for path in paths]
    checks = {
        "openapi_primary": primary.get("provider") == "LS_OPENAPI" and primary["rows"],
        "t8451_paging": len(paged["rows"]) == 2 and json.loads(session.calls[2][1]["data"])["t8451InBlock"]["qrycnt"] == 500 and session.calls[3][1]["headers"]["tr_cont"] == "Y",
        "xing_fallback": fallback.connected and delegated["rows"][0]["fallback"] == "t8424",
        "provider_fail_fast": unavailable,
        "menu5_adaptive": "AdaptiveRawTrBridge" in texts[1], "menu7_adaptive": "AdaptiveRawTrBridge" in texts[2],
        "postgresql_preserved": "PostgreSQLXingMenuRepository" in texts[1] + texts[2],
        "canonical_root": all("My_stocks" not in text and r"Users\PLATINUM\new_stock" not in text for text in texts),
        "no_sqlite": all("sqlite" not in text.lower() for text in texts),
    }
    for name, passed in checks.items(): print(f"{name}: {'PASS' if passed else 'FAIL'}")
    print(f"V44_OPENAPI_PRIMARY_VERIFY: {'PASS' if all(checks.values()) else 'FAIL'}")
    return 0 if all(checks.values()) else 3


if __name__ == "__main__": raise SystemExit(main())
