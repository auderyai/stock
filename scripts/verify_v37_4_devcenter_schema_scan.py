from pathlib import Path
import ast

root = Path(__file__).resolve().parents[1]
path = root / "scripts/scan_xing_devcenter_schema_sources_gui.py"
text = path.read_text(encoding="utf-8")
ast.parse(text)

for marker in (
    r'C:\LS_SEC\xingAPI_Program(2025.06.07)',
    '"t8424", "t8436", "t1516", "t8429", "t8451", "t1702"',
    "read_bytes()",
    "utf-16le",
    "utf-16be",
    "여러 필수 TR가 함께 발견된 폴더",
):
    assert marker in text, marker

assert "write_bytes" not in text
assert "unlink(" not in text
assert "rmtree(" not in text

print("V37_4_DEVCENTER_SCHEMA_SOURCE_SCAN_CHECK: PASS")
