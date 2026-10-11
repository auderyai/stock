from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

files = [
    ROOT / "src/krx_research/collectors/xingdll/direct.py",
    ROOT / "src/krx_research/collectors/xing/worker_runtime.py",
    ROOT / "src/krx_research/collectors/xing/bridge.py",
    ROOT / "scripts/xing32_worker.py",
]
for path in files:
    ast.parse(path.read_text(encoding="utf-8"))

direct = files[0].read_text(encoding="utf-8")
assert "ETK_Request" in direct
assert "RECV_PACKET" in direct
assert "MSG_PACKET" in direct
assert "TrSchemaService" in direct
assert "PacketCodec" in direct
assert "ResFileName" not in direct
assert "win32com" not in direct
assert "XA_Session" not in direct
assert "ctypes.sizeof(RECV_PACKET) != 103" in direct
assert "if not state.continuation:" in direct

runtime = files[1].read_text(encoding="utf-8")
assert "com_registered" not in runtime
assert "XingAPI.dll" in runtime

worker = files[3].read_text(encoding="utf-8")
assert "XingDllSession" in worker
assert "XingQueryClient" not in worker
assert "XingSession" not in worker

# Menu 2/5/7 high-level scripts must remain on the common facade.
for script in (
    "update_xing_index_membership.py",
    "update_ls_investor_raw.py",
    "update_ls_investor_date_range.py",
    "update_xing_venue_history.py",
):
    text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
    assert "XA_Session" not in text
    assert "win32com" not in text

print("V38_FINAL_DLL_RUNTIME_STATIC_CHECK: PASS")
