from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')

checks = {
    'weekly screen titles': all(key in read('src/krx_research/ui/data.py') for key in (
        'kospi_weekly_trading_value', 'kosdaq_weekly_trading_value', 'kospi_kosdaq_weekly_trading_value')),
    'common rank widget': 'class RankLimitControl' in read('src/krx_research/qt/widgets/rank_limit_control.py'),
    'query top_n': 'top_n: int = 50' in read('src/krx_research/qt/models/screen_query.py'),
    'main query uses rank control': 'self.rank_limit = RankLimitControl(50)' in read('src/krx_research/qt/widgets/query_panel.py'),
    'investor uses rank control': 'self.rank_limit = RankLimitControl(10)' in read('src/krx_research/qt/windows/investor_dashboard_window.py'),
    'service applies global limit': 'return self._limit(dataset, query.top_n)' in read('src/krx_research/qt/services/screening_service.py'),
    'weekly value aggregation': 'weekly_trading_value_eok' in read('src/krx_research/ui/on_demand.py'),
    'weekly eok label': '주간 거래대금(억원)' in read('src/krx_research/qt/presentation/column_catalog.py'),
    'investor no fixed head10': '.head(10)' not in read('src/krx_research/ui/data.py')[read('src/krx_research/ui/data.py').find('def build_investor_flow_rows'):read('src/krx_research/ui/data.py').find('def overlay_realtime_quotes')],
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit('V19 check failed: ' + ', '.join(failed))
print('V19_DYNAMIC_RANK_WEEKLY_VALUE_CHECK: PASS')
