from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing_schema.codec import PacketCodec
from krx_research.collectors.xing_schema.model import BlockSchema, FieldSchema


def main() -> int:
    codec = PacketCodec()

    # Exact current t8424OutBlock: hname 20 + upcode 3 = schema body 23.
    block = BlockSchema(
        name="t8424OutBlock",
        direction="output",
        occurs=True,
        fields=(
            FieldSchema("hname", "string", 20),
            FieldSchema("upcode", "string", 3),
        ),
    )
    assert block.size == 23
    assert len(block.fields) == 2
    assert codec._field_nul_wire_size(block) == 25

    hname = b"KOSPI               "
    upcode = b"001"
    assert len(hname) == 20
    assert len(upcode) == 3

    wire_row = hname + b"\x00" + upcode + b"\x00"
    assert len(wire_row) == 25

    # Matches the user's live DLL packet length exactly:
    # 25 bytes/row * 252 rows = 6300 bytes.
    packet = wire_row * 252
    assert len(packet) == 6300

    rows = codec.decode_occurs(block, packet)
    assert len(rows) == 252
    assert rows[0]["hname"] == "KOSPI"
    assert rows[0]["upcode"] == "001"

    # Packed form remains supported for schemas/sources that return it.
    packed_row = hname + upcode
    packed_rows = codec.decode_occurs(block, packed_row * 2)
    assert len(packed_rows) == 2

    # Wrong field delimiter must never be silently accepted.
    bad = hname + b"X" + upcode + b"\x00"
    try:
        codec.decode_occurs(block, bad)
    except ValueError:
        pass
    else:
        raise AssertionError("non-NUL field delimiter must fail")

    print("V38_4_FIELD_TERMINATED_WIRE_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
