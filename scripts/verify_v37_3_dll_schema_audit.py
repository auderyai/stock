from pathlib import Path
import ast

root=Path(__file__).resolve().parents[1]
paths=[
    root/"src/krx_research/collectors/xingdll/readiness.py",
    root/"scripts/audit_xing_dll_packet_schemas_gui.py",
]
for p in paths:
    ast.parse(p.read_text(encoding="utf-8"))

r=paths[0].read_text(encoding="utf-8")
assert "runtime_ready" in r
assert "require_runtime_ready" in r
assert "resources" in r and "schemas" in r
assert "t8451" in r

a=paths[1].read_text(encoding="utf-8")
assert "PacketZipAudit" in a
assert "runtime schema로 승격하지 않습니다" in a

print("V37_3_DLL_SCHEMA_AUDIT_CHECK: PASS")
