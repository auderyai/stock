from pathlib import Path
import ast

root = Path(__file__).resolve().parents[1]
query = root / "src/krx_research/collectors/xing/query.py"
setup = root / "scripts/setup_xing_res_dir_gui.py"

q = query.read_text(encoding="utf-8")
s = setup.read_text(encoding="utf-8")
ast.parse(q)
ast.parse(s)

assert 'resources" / "xing" / "res"' in q
assert "Downloads" not in q
assert "DevCenter" not in q
assert "selected_path != self.managed" in s
assert "필수 RES 파일 누락" in s
assert "EnvRepository(ROOT / \".env\")" in s

managed = root / "resources" / "xing" / "res"
managed.mkdir(parents=True, exist_ok=True)

print("V36_6_MANAGED_RES_DIRECTORY_CHECK: PASS")
print(f"managed_res={managed}")
