from pathlib import Path
import ast
root=Path(__file__).resolve().parents[1]
files=[
 root/"src/krx_research/collectors/xing/session.py",
 root/"src/krx_research/collectors/xing/query.py",
 root/"src/krx_research/collectors/xing/bridge.py",
 root/"scripts/xing32_worker.py",
 root/"scripts/test_xing32_connection.py",
 root/"scripts/test_xing32_connection_gui.py",
 root/"tools/setup/TEST_XINGAPI_CONNECTION.cmd",
 root/"tools/setup/SETUP_XINGAPI_CREDENTIALS_ONCE.cmd",
]
assert all(p.is_file() for p in files)
for p in files:
    if p.suffix==".py": ast.parse(p.read_text(encoding="utf-8"))
assert 'operation": "health"' in (root/"src/krx_research/collectors/xing/bridge.py").read_text(encoding="utf-8")
assert '"health"' in (root/"scripts/xing32_worker.py").read_text(encoding="utf-8")
assert "CoInitialize" in (root/"src/krx_research/collectors/xing/session.py").read_text(encoding="utf-8")
print("V36_1_XING_CONNECTION_HARDENING_CHECK: PASS")
