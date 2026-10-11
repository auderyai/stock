from pathlib import Path
import ast

root = Path(__file__).resolve().parents[1]
path = root / "src/krx_research/collectors/xing/query.py"
text = path.read_text(encoding="utf-8")
ast.parse(text)

for marker in (
    "_devcenter_roots",
    "home / \"Downloads\"",
    "home / \"Desktop\"",
    "home / \"Documents\"",
    "ranked_roots",
    "_score",
    "@lru_cache",
):
    assert marker in text, marker

print("V36_4_DEV_CENTER_RES_DISCOVERY_CHECK: PASS")
