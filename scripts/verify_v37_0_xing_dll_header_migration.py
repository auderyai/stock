from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]

files = [
    ROOT / "src/krx_research/collectors/xingdll/runtime.py",
    ROOT / "scripts/check_xing_dll_header_gui.py",
    ROOT / "scripts/remove_obsolete_xing_res_config.py",
]
for path in files:
    ast.parse(path.read_text(encoding="utf-8"))

runtime = files[0].read_text(encoding="utf-8")
assert "XingAPI.dll" in runtime
assert "ETK_Request" in runtime
assert "_latest_version_dir" in runtime
assert 'resources" / "xing" / "headers"' in runtime
assert "ResFileName" not in runtime
assert "LS_XING_RES_DIR" not in runtime

print("V37_0_XING_DLL_HEADER_MIGRATION_CHECK: PASS")
