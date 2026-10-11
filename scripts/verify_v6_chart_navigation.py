from __future__ import annotations

import ast
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

required = [
    'src/krx_research/qt/strategies/chart_navigation.py',
    'src/krx_research/qt/presentation/table_policy.py',
    'src/krx_research/qt/widgets/result_table.py',
    'src/krx_research/qt/windows/chart_window.py',
    'src/krx_research/qt/controllers/chart_controller.py',
    'src/krx_research/qt/controllers/workstation_controller.py',
    'src/krx_research/qt/services/investor_dashboard_service.py',
    'src/krx_research/qt/controllers/investor_dashboard_controller.py',
    'src/krx_research/qt/windows/investor_dashboard_window.py',
    'src/krx_research/qt/services/market_index_service.py',
    'src/krx_research/qt/controllers/market_index_controller.py',
    'src/krx_research/qt/windows/market_index_window.py',
]
for rel in required:
    if not (ROOT / rel).exists():
        errors.append(f'missing: {rel}')

strategy = (ROOT / 'src/krx_research/qt/strategies/chart_navigation.py').read_text(encoding='utf-8')
for token in ('NewChartWindowStrategy', 'SynchronizedChartStrategy', 'navigation_enabled=False', 'navigation_enabled=True'):
    if token not in strategy:
        errors.append(f'chart strategy missing token: {token}')

chart_view = (ROOT / 'src/krx_research/qt/windows/chart_window.py').read_text(encoding='utf-8')
for token in ('QSplitter', 'navigationTickerChanged', 'ResultTable', 'set_navigation_results', 'select_navigation_ticker'):
    if token not in chart_view:
        errors.append(f'chart result-list navigation missing: {token}')

result_table = (ROOT / 'src/krx_research/qt/widgets/result_table.py').read_text(encoding='utf-8')
for token in ('currentTickerChanged', 'select_ticker', 'SelectRows'):
    if token not in result_table:
        errors.append(f'result table navigation missing: {token}')

policy = (ROOT / 'src/krx_research/qt/presentation/table_policy.py').read_text(encoding='utf-8')
for token in ('trade_date', 'trading_value', 'source_file', 'volume_columns', 'AlignCenter', 'AlignRight'):
    if token not in policy:
        errors.append(f'table policy missing: {token}')

# Every pure Qt view/controller must remain free of database/repository imports and SQL.
for folder_name in ('windows', 'widgets', 'controllers'):
    folder = ROOT / 'src/krx_research/qt' / folder_name
    for path in folder.rglob('*.py'):
        text = path.read_text(encoding='utf-8')
        low = text.lower()
        if 'tkinter' in low or 'figurecanvastkagg' in low or 'pyqt' in low:
            errors.append(f'non-PySide6 UI technology: {path.relative_to(ROOT)}')
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or '']
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                if module.startswith(('krx_research.database', 'krx_research.data_engine.postgresql')):
                    errors.append(f'view/controller reaches database directly: {path.relative_to(ROOT)} -> {module}')
        if re.search(r'(?is)\bselect\b.+?\bfrom\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b|\bdelete\s+from\b', text):
            errors.append(f'raw SQL in view/controller: {path.relative_to(ROOT)}')

print('V6_CHART_NAVIGATION_CHECK:', 'PASS' if not errors else 'FAIL')
for error in errors:
    print(' -', error)
sys.exit(1 if errors else 0)
