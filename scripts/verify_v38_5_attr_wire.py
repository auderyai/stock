from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing_schema import (
    BlockSchema, FieldSchema, JsonSchemaLoader, PacketCodec, ResSchemaLoader
)


SAMPLE_RES = """BEGIN_FUNCTION_MAP
.Func,업종전체조회,t8424,attr,headtype=A;
BEGIN_DATA_MAP
t8424InBlock,기본입력,input;
begin
구분1,gubun1,gubun1,char,1;
end
t8424OutBlock,출력,output,occurs;
begin
업종명,hname,hname,char,20;
업종코드,upcode,upcode,char,3;
end
END_DATA_MAP
END_FUNCTION_MAP
"""


def main() -> int:
    codec = PacketCodec()

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t8424.res"
        p.write_text(SAMPLE_RES, encoding="cp949")
        schema = ResSchemaLoader().load(p)

    in_block = schema.block("t8424InBlock")
    out_block = schema.block("t8424OutBlock")

    assert in_block.is_attr is True
    assert out_block.is_attr is True
    assert out_block.size == 23
    assert len(out_block.fields) == 2
    assert out_block.wire_size == 25

    # Input must append one ASCII-space attr byte after the field.
    assert codec.encode(in_block, {"gubun1": "0"}) == b"0 "

    # Live-user arithmetic: 23 schema bytes + 2 attr bytes = 25.
    # The observed first attr byte was 0x20. The decoder intentionally ignores
    # attr-byte values, exactly as the native parser does.
    hname = b"KOSPI               "
    upcode = b"001"
    row = hname + b"\x20" + upcode + b"\x20"
    assert len(row) == 25

    packet = row * 252
    assert len(packet) == 6300
    rows = codec.decode_occurs(out_block, packet)
    assert len(rows) == 252
    assert rows[0]["hname"] == "KOSPI"
    assert rows[0]["upcode"] == "001"

    # Attribute value is framing/meta, not data. Do not hardcode its value.
    row2 = hname + b"\x7f" + upcode + b"\x01"
    decoded = codec.decode_occurs(out_block, row2)
    assert decoded[0]["hname"] == "KOSPI"
    assert decoded[0]["upcode"] == "001"

    # Non-attr blocks remain packed.
    packed = BlockSchema(
        name="Packed",
        direction="output",
        occurs=True,
        fields=(FieldSchema("a", "string", 2), FieldSchema("b", "string", 3)),
        is_attr=False,
    )
    assert packed.size == 5
    assert packed.wire_size == 5
    assert codec.decode_occurs(packed, b"AA123")[0] == {"a": "AA", "b": "123"}

    # Project JSON schemas must carry DevCenter Attribute=O.
    for tr in ("t1516", "t1702"):
        path = ROOT / "resources" / "xing" / "schemas" / f"{tr}.json"
        schema = JsonSchemaLoader().load(path)
        assert all(block.is_attr for block in schema.blocks), tr

    print("V38_5_ATTR_WIRE_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
