from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")

data = read("src/krx_research/ui/data.py")
on_demand = read("src/krx_research/ui/on_demand.py")
query_panel = read("src/krx_research/qt/widgets/query_panel.py")
rank_widget = read("src/krx_research/qt/widgets/rank_limit_control.py")
service = read("src/krx_research/qt/services/screening_service.py")

checks = {
    "KOSPI weekly screen": '"kospi_weekly_gainers": "KOSPI 주간 상승률 Top 50"' in data,
    "KOSDAQ weekly screen": '"kosdaq_weekly_gainers": "KOSDAQ 주간 상승률 Top 50"' in data,
    "combined weekly screen": '"weekly_return": "KOSPI+KOSDAQ 주간 상승률 Top 50"' in data,
    "weekly market definition": all(token in data for token in (
        '"kospi_weekly_gainers": "KOSPI"',
        '"kosdaq_weekly_gainers": "KOSDAQ"',
        '"weekly_return": "KOSPI+KOSDAQ"',
    )),
    "weekly ranking metric": 'frame["weekly_return_pct"]' in data and 'MARKET_WEEKLY_GAINER_SCREEN_TYPES' in data,
    "weekly period semantics": 'MARKET_WEEKLY_GAINER_SCREEN_TYPES' in data and 'WEEKLY_SCREEN_TYPES' in data,
    "on-demand lookback": all(token in on_demand for token in (
        '"kospi_weekly_gainers": 45', '"kosdaq_weekly_gainers": 45')),
    "common rank widget": "class RankLimitControl" in rank_widget,
    "main rank control": "self.rank_limit = RankLimitControl(50)" in query_panel,
    "service global top-n": "return self._limit(dataset, query.top_n)" in service,
    "default top-n 50": all(f'"{key}": 50' in data for key in (
        "kospi_weekly_gainers", "kosdaq_weekly_gainers", "weekly_return")),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("V20 check failed: " + ", ".join(failed))
print("V20_WEEKLY_GAINERS_TOPN_CHECK: PASS")
