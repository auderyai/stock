from __future__ import annotations

from pathlib import Path
import ast
import sys

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
paths = {
    'view': ROOT/'src/krx_research/qt/windows/market_index_window.py',
    'controller': ROOT/'src/krx_research/qt/controllers/market_index_controller.py',
    'service': ROOT/'src/krx_research/qt/services/market_index_service.py',
    'controls': ROOT/'src/krx_research/qt/widgets/chart_controls.py',
    'chart': ROOT/'src/krx_research/qt/windows/chart_window.py',
}
texts = {k:p.read_text(encoding='utf-8') for k,p in paths.items() if p.exists()}
for k,p in paths.items():
    if not p.exists(): errors.append(f'missing: {p.relative_to(ROOT)}')

def need(key: str, needle: str, msg: str):
    if needle not in texts.get(key, ''): errors.append(msg)

# Original workstation feature parity.
need('view', 'ChartControlPanel(default_days=800, include_investor=False)', 'index chart must reuse common original-style chart controls')
need('view', 'ClassicStrategyPanel()', 'index chart must include classic-strategy panel')
need('view', 'QSplitter(Qt.Horizontal)', 'navigation mode must keep movable index list')
need('view', 'self.combo.currentIndexChanged.connect(self._combo_changed)', 'non-navigation combo must switch immediately')
need('view', 'self.strategyRefreshRequested.emit', 'index chart must refresh strategy when chart window changes')
need('controller', 'view.scenarioRequested.connect(self.open_scenario)', 'index chart must open indicator scenario')
need('controller', 'view.strategyRefreshRequested.connect(self.refresh_strategy)', 'controller must orchestrate strategy refresh')
need('service', 'select_chart_window', 'service must assess strategy on visible chart window')
need('service', 'assess_classic_strategies', 'service must own classic strategy calculation')
need('controls', '봉 주기', 'common controls missing timeframe')
need('controls', '표시 봉수', 'common controls missing visible-bar input')
need('controls', '매물대 구간', 'common controls missing profile bins')
need('controls', '보조지표 시나리오·AI', 'common controls missing scenario button')
for label in ('거래량','RSI(14,9)','MACD 오실레이터','스토캐스틱 슬로우(5,3,3)'):
    need('controls', label, f'common controls missing {label}')
need('chart', 'ChartControlPanel(default_days=500, include_investor=True)', 'stock chart must reuse common controls instead of duplicate code')
need('chart', 'ClassicStrategyPanel()', 'stock chart must reuse common strategy panel')

# Layer rules: view/controller/service must remain DB-free, View is PySide6-only.
for key in ('view','controller','service','controls','chart'):
    text = texts.get(key, '')
    low = text.lower()
    if 'tkinter' in low or 'figurecanvastkagg' in low or 'pyqt5' in low or 'pyqt6' in low:
        errors.append(f'non-PySide6 GUI dependency in {key}')
for key in ('view','controller','service','controls'):
    if not texts.get(key): continue
    tree = ast.parse(texts[key], filename=str(paths[key]))
    for node in ast.walk(tree):
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            modules=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or '']
            if any(m.startswith(('krx_research.database','krx_research.data_engine.postgresql')) for m in modules):
                errors.append(f'DB access escaped repository layer: {paths[key].relative_to(ROOT)}')

print('V14_MARKET_INDEX_PARITY_CHECK:', 'PASS' if not errors else 'FAIL')
for e in errors: print(' -', e)
sys.exit(1 if errors else 0)
