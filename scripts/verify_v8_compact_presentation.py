from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
QT = ROOT / 'src' / 'krx_research' / 'qt'
errors: list[str] = []

policy = (QT / 'presentation' / 'table_policy.py').read_text(encoding='utf-8')
for token in (
    'market_cap_columns', 'cash_value_columns', '100_000_000.0:,.1f',
    'center_columns: tuple[str, ...] = ("flow_direction",)',
):
    if token not in policy:
        errors.append(f'missing common presentation rule: {token}')

catalog = (QT / 'presentation' / 'column_catalog.py').read_text(encoding='utf-8')
for token in ('"market_cap": "시가총액(억원)"', '"buy_value": "매수대금(억원)"', '"sell_value": "매도대금(억원)"'):
    if token not in catalog:
        errors.append(f'missing Korean unit label: {token}')

result_table = (QT / 'widgets' / 'result_table.py').read_text(encoding='utf-8')
for token in ('QHeaderView.Interactive', 'setSectionsMovable(True)'):
    if token not in result_table:
        errors.append(f'missing user-adjustable table header behavior: {token}')

# Enforce the compact architecture: these global rules must exist once in the
# shared presentation/table classes, not be duplicated in every window.
for window in (QT / 'windows').glob('*.py'):
    text = window.read_text(encoding='utf-8')
    if '/ 100_000_000' in text or '/100_000_000' in text:
        errors.append(f'unit conversion duplicated in View: {window.name}')

print('V8_COMPACT_PRESENTATION_CHECK:', 'PASS' if not errors else 'FAIL')
for error in errors:
    print(' -', error)
sys.exit(1 if errors else 0)
