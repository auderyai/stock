from pathlib import Path
import ast

root = Path(__file__).resolve().parents[1]
query = root / "src/krx_research/collectors/xing/query.py"
setup = root / "scripts/setup_xing_res_dir_gui.py"

qt = query.read_text(encoding="utf-8")
st = setup.read_text(encoding="utf-8")
ast.parse(qt)
ast.parse(st)

assert "LS_XING_RES_DIR" in qt
assert "_env_value" in qt
assert 'ROOT / ".env"' in st
assert "QFileDialog.getExistingDirectory" in st
assert "EnvRepository" in st

print("V36_5_XING_RES_DIR_SETUP_CHECK: PASS")
