from pathlib import Path
import ast

root=Path(__file__).resolve().parents[1]
runtime=root/"src/krx_research/collectors/xingdll/runtime.py"
gui=root/"scripts/check_xing_dll_header_gui.py"

for p in (runtime,gui):
    ast.parse(p.read_text(encoding="utf-8"))

text=runtime.read_text(encoding="utf-8")
assert "xingAPI_Program" in text
assert "discover_install_root" in text
assert "candidates.sort" in text
assert 'legacy = base / "xingAPI"' in text
assert "XingAPI.dll" in text

print("V37_1_XING_INSTALL_ROOT_FIX_CHECK: PASS")
