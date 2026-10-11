from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
menu = (ROOT / "KRX_Menu_Launcher/scripts/run_krx_menu.py").read_text(encoding="utf-8")
progress = (ROOT / "KRX_Menu_Launcher/scripts/run_job_progress_gui.py").read_text(encoding="utf-8")
date_gui = (ROOT / "KRX_Menu_Launcher/scripts/run_investor_date_range_gui.py").read_text(encoding="utf-8")
integrated = (ROOT / "scripts/run_daily_integrated.py").read_text(encoding="utf-8")
date_script = (ROOT / "scripts/update_ls_investor_date_range.py").read_text(encoding="utf-8")

checks = {
    "menu investor date range": "5. LS 수급 원본 갱신 (날짜 지정)" in menu,
    "menu supplement": "7. LS 종목별 일봉·수급 원본 보완" in menu,
    "launcher mode": 'mode="launcher"' in menu,
    "progress supplement": '"supplement"' in progress and '"--ls-supplement"' in progress,
    "date range PySide6": "from PySide6" in date_gui and "tkinter" not in date_gui,
    "date range controller": "class DateRangeController" in date_gui,
    "date range script": "update_ls_investor_date_range.py" in date_gui,
    "supplement backend": "--ls-supplement" in integrated and "update_ls_investor_raw.py" in integrated,
    "postgres date storage": "market_core.ls_investor_t1702_raw" in date_script,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("V22_LS_LAUNCHER_CHECK: FAIL: " + ", ".join(failed))
print("V22_LS_LAUNCHER_CHECK: PASS")
