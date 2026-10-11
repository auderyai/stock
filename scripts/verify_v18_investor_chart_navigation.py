from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
view = (ROOT / 'src/krx_research/qt/windows/investor_dashboard_window.py').read_text(encoding='utf-8')
controller = (ROOT / 'src/krx_research/qt/controllers/investor_dashboard_controller.py').read_text(encoding='utf-8')
factory = (ROOT / 'src/krx_research/qt/application/window_factory.py').read_text(encoding='utf-8')
workstation = (ROOT / 'src/krx_research/qt/controllers/workstation_controller.py').read_text(encoding='utf-8')
data = (ROOT / 'src/krx_research/ui/data.py').read_text(encoding='utf-8')

checks = {
    'dashboard emits frame+labels': 'Signal(str, object, object)' in view and 'table.frame.copy(deep=False)' in view,
    'controller reuses chart strategies': 'SynchronizedChartStrategy' in controller and 'NewChartWindowStrategy' in controller,
    'navigate flag wired through factory': 'navigate: bool' in factory and 'navigate=navigate' in factory,
    'workstation forwards checkbox state': 'navigate=self.view.synchronized_chart_enabled()' in workstation,
    'duplicated investor screens removed': 'SCREEN_TITLES.update({' not in data,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit('V18_CHECK FAIL: ' + ', '.join(failed))
print('V18_INVESTOR_CHART_NAVIGATION_CHECK: PASS')
