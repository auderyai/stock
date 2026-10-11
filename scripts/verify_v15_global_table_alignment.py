from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
QT = ROOT / 'src' / 'krx_research' / 'qt'
errors: list[str] = []

policy_path = QT / 'presentation' / 'table_policy.py'
common_path = QT / 'common.py'
market_path = QT / 'windows' / 'market_index_window.py'
result_table_path = QT / 'widgets' / 'result_table.py'

policy = policy_path.read_text(encoding='utf-8')
common = common_path.read_text(encoding='utf-8')
market = market_path.read_text(encoding='utf-8')
result_table = result_table_path.read_text(encoding='utf-8')

checks = {
    'global numeric-text detector': '_is_numeric_like' in policy and '_NUMERIC_TEXT' in policy,
    'numeric cells right aligned': 'Qt.AlignRight | Qt.AlignVCenter' in policy,
    'text cells left aligned': 'Qt.AlignLeft | Qt.AlignVCenter' in policy,
    'stock/index codes centered': '"index_code"' in policy and 'if column in self.ticker_columns' in policy,
    'headers use common alignment policy': 'self._policy.header_alignment' in common,
    'market-index market not forced centered': 'center_columns=("market", "index_code")' not in market,
    'market-index code centered': 'center_columns=("index_code",)' in market,
    'market-index numeric columns explicit right': 'right_columns=("level", "daily_return", "weekly_return", "trading_value_eok", "previous_trading_value_eok")' in market,
    'all PySide6 result grids share DataFrameModel': 'DataFrameModel' in result_table,
    'columns remain user-resizable': 'QHeaderView.Interactive' in result_table,
}
for name, ok in checks.items():
    if not ok:
        errors.append(name)

# The Qt tree must not bypass the shared table model with ad-hoc table widgets.
for path in QT.rglob('*.py'):
    text = path.read_text(encoding='utf-8')
    if path == result_table_path:
        continue
    if 'QTableWidget' in text or 'QTableView' in text:
        errors.append(f'ad-hoc Qt table bypasses shared policy: {path.relative_to(ROOT)}')

print('V15_GLOBAL_TABLE_ALIGNMENT_CHECK:', 'PASS' if not errors else 'FAIL')
for error in errors:
    print(' -', error)
sys.exit(1 if errors else 0)
