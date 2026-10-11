from __future__ import annotations

from pathlib import Path
import ast
import sys

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

view = ROOT / 'src/krx_research/qt/windows/market_index_window.py'
controller = ROOT / 'src/krx_research/qt/controllers/market_index_controller.py'
service = ROOT / 'src/krx_research/qt/services/market_index_service.py'
repo = ROOT / 'src/krx_research/qt/repositories/market_index_repository.py'
factory = ROOT / 'src/krx_research/qt/application/window_factory.py'
workstation = ROOT / 'src/krx_research/qt/controllers/workstation_controller.py'
result_table = ROOT / 'src/krx_research/qt/widgets/result_table.py'

for p in (view, controller, service, repo, factory, workstation, result_table):
    if not p.exists():
        errors.append(f'missing: {p.relative_to(ROOT)}')

texts = {p: p.read_text(encoding='utf-8') for p in (view, controller, service, repo, factory, workstation, result_table) if p.exists()}

def require(path: Path, needle: str, message: str) -> None:
    if needle not in texts.get(path, ''):
        errors.append(message)

require(view, 'QSplitter(Qt.Horizontal)', 'navigation mode must use movable PySide6 QSplitter')
require(view, 'identity_columns=("index_code",)', 'index navigation table must use index_code identity')
require(view, 'self.index_table.currentTickerChanged.connect(self.indexRequested.emit)', 'click/up/down row changes must request a new index chart')
require(view, 'self.combo.currentIndexChanged.connect(self._combo_changed)', 'non-navigation combo must redraw immediately on index change')
require(controller, 'self._requested_code', 'controller must reject stale async index responses')
require(service, 'list_overview', 'service must build the right-side index overview')
require(repo, 'index_list_snapshots', 'repository must load overview snapshots through SQL data layer')
require(repo, 'fetch_index', 'repository must load index candles through SQL data layer')
require(factory, 'MarketIndexRepository', 'composition root must wire MarketIndexRepository')
require(factory, 'navigate: bool', 'factory must receive navigation mode explicitly')
require(workstation, 'navigate=self.view.synchronized_chart_enabled()', 'workstation result-navigation setting must control index-window mode')
require(result_table, 'identity_columns:', 'common ResultTable must support reusable identities instead of duplicate index widgets')

# Strict layer guard: PySide6 view/controller/service must not open PostgreSQL connections directly.
for p in (view, controller, service):
    tree = ast.parse(texts.get(p, ''), filename=str(p))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
            if any(name.startswith('krx_research.data_engine.postgresql') for name in modules):
                errors.append(f'database access escaped repository layer: {p.relative_to(ROOT)}')

# PySide6-only regression guard for this feature.
for p in (view, controller):
    low = texts.get(p, '').lower()
    if 'tkinter' in low or 'pyqt5' in low or 'pyqt6' in low or 'figurecanvastkagg' in low:
        errors.append(f'non-PySide6 GUI dependency: {p.relative_to(ROOT)}')

print('V12_MARKET_INDEX_NAVIGATION_CHECK:', 'PASS' if not errors else 'FAIL')
for error in errors:
    print(' -', error)
sys.exit(1 if errors else 0)
