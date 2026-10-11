from pathlib import Path
import ast

root = Path(__file__).resolve().parents[1]
paths = [
    root / "src/krx_research/collectors/xingdll/runtime.py",
    root / "scripts/probe_xing_dll_exports_32.py",
    root / "scripts/check_xing_dll_header_gui.py",
]
for p in paths:
    ast.parse(p.read_text(encoding="utf-8"))

runtime = paths[0].read_text(encoding="utf-8")
assert ".venv_xing32" in runtime
assert "probe_exports_32bit" in runtime
assert "res_root" in runtime
assert "required_res" in runtime

probe = paths[1].read_text(encoding="utf-8")
assert 'bits != 32' in probe
assert 'ctypes.WinDLL' in probe
assert 'ETK_Request' in probe

print("V37_2_XING32_DLL_PROBE_CHECK: PASS")
