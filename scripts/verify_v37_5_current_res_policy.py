from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing_schema import CURRENT_RES_TRS, BLOCKED_TRS

assert CURRENT_RES_TRS == ("t8424", "t8436", "t8429", "t8451")
assert BLOCKED_TRS == ("t1516", "t1702")

print("V37_5_CURRENT_RES_POLICY_CHECK: PASS")
