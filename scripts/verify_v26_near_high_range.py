from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
query = (ROOT / 'src/krx_research/qt/widgets/query_panel.py').read_text(encoding='utf-8')
selector = (ROOT / 'src/krx_research/qt/widgets/screen_selector.py').read_text(encoding='utf-8')
controller = (ROOT / 'src/krx_research/qt/controllers/workstation_controller.py').read_text(encoding='utf-8')
service = (ROOT / 'src/krx_research/qt/services/screening_service.py').read_text(encoding='utf-8')
data = (ROOT / 'src/krx_research/ui/data.py').read_text(encoding='utf-8')
model = (ROOT / 'src/krx_research/qt/models/screen_query.py').read_text(encoding='utf-8')

for src in (query, selector, controller, service, data, model):
    ast.parse(src)

assert 'QGroupBox("52주 최고가 대비 종가 (%)")' in query
assert 'self.near_low.setValue(-10)' in query
assert 'self.near_high.setValue(0)' in query
assert 'QPushButton("구간 검색")' in query
assert 'near52wRequested = Signal()' in query
assert 'returnPressed.connect(self._request_near52w)' in query
assert 'key != "near_high_52w"' in selector
assert 'def run_near_52w' in controller
assert 'self._run_screen_key("near_high_52w")' in controller
assert 'filter_52w_distance(dataset, query.near_52w_low, query.near_52w_high)' in service
assert 'values.ge(lower) & values.le(upper)' in data
assert 'near_52w_low: float = -10.0' in model
print('V26_NEAR_HIGH_RANGE_CHECK: PASS')
