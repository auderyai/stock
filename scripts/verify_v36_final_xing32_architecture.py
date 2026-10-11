from pathlib import Path
import ast
root=Path(__file__).resolve().parents[1]
required=[root/'src/krx_research/collectors/xing/bridge.py',root/'src/krx_research/collectors/xing/worker_runtime.py',root/'scripts/xing32_worker.py',root/'tools/setup/SETUP_XING32_ENV.cmd',root/'tools/setup/CHECK_XINGAPI_RUNTIME.cmd']
assert all(p.is_file() for p in required)
ls=(root/'src/krx_research/collectors/ls_index_api.py').read_text(encoding='utf-8'); price=(root/'src/krx_research/collectors/xing_t8451.py').read_text(encoding='utf-8')
assert 'XingBridgeClient' in ls and 'XingSession' not in ls
assert 'XingBridgeClient' in price and 'XingSession' not in price
for n in ('update_ls_investor_raw.py','update_ls_investor_date_range.py'): assert '.api.token()' not in (root/'scripts'/n).read_text(encoding='utf-8')
assert 'client.api.fetch' not in (root/'scripts/repair_ls_screen_day.py').read_text(encoding='utf-8')
worker=(root/'scripts/xing32_worker.py').read_text(encoding='utf-8'); assert 'struct.calcsize("P") * 8 != 32' in worker and 'XingSession' in worker
for p in required[:3]: ast.parse(p.read_text(encoding='utf-8'))
print('V36_FINAL_XING32_ARCHITECTURE_CHECK: PASS')
