from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing_schema import UnifiedSchemaReadiness

schema_dir = ROOT / "resources" / "xing" / "schemas"

t1516 = json.loads((schema_dir / "t1516.json").read_text(encoding="utf-8"))
t1702 = json.loads((schema_dir / "t1702.json").read_text(encoding="utf-8"))

assert t1516["total_size"] == 205
assert [b["size"] for b in t1516["blocks"]] == [10, 32, 163]
assert t1702["total_size"] == 261
assert [b["size"] for b in t1702["blocks"]] == [26, 235]

def calc(block):
    return sum(f["size"] for f in block["fields"])

for doc in (t1516, t1702):
    for block in doc["blocks"]:
        assert calc(block) == block["size"], (doc["tr_code"], block["name"], calc(block), block["size"])

print("V37_6_T1516_T1702_SCHEMA_PROMOTION_CHECK: PASS")
