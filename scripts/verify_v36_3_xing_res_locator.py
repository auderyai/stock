from pathlib import Path
import ast

root = Path(__file__).resolve().parents[1]
query = root / "src" / "krx_research" / "collectors" / "xing" / "query.py"
text = query.read_text(encoding="utf-8")
tree = ast.parse(text)

assert "class XingResLocator" in text
assert "KEY_WOW64_32KEY" in text
assert "InprocServer32" in text
assert "LS_XING_RES_DIR" in text
assert "_limited_recursive" in text
assert "@lru_cache" in text
assert "ResLocator = XingResLocator" in text

print("V36_3_XING_RES_LOCATOR_CHECK: PASS")
