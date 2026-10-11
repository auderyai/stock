from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
policy = (ROOT / 'src/krx_research/qt/presentation/chart_navigation_policy.py').read_text(encoding='utf-8')
chart = (ROOT / 'src/krx_research/qt/windows/chart_window.py').read_text(encoding='utf-8')
result_table = (ROOT / 'src/krx_research/qt/widgets/result_table.py').read_text(encoding='utf-8')

assert 'ChartNavigationPresentationPolicy' in policy
assert 'date_reference_columns' in policy
assert 'CHART_NAVIGATION_TABLE_POLICY' in chart
assert 'ResultTable(policy=CHART_NAVIGATION_TABLE_POLICY)' in chart
assert 'policy: TablePresentationPolicy | None = None' in result_table
print('V9_CHART_DATE_HIDDEN_CHECK: PASS')
