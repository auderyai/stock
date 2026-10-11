from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing_schema.codec import PacketCodec
from krx_research.collectors.xing_schema.model import BlockSchema, FieldSchema


def main() -> int:
    codec = PacketCodec()
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

    one = b"KOSPI               " + b"001"
    assert len(one) == 23

    compact = one * 3
    rows = codec.decode_occurs(block, compact)
    assert len(rows) == 3

    framed = (one + b"\r\n") * 252
    assert len(framed) == 6300
    rows = codec.decode_occurs(block, framed)
    assert len(rows) == 252
    assert rows[0]["hname"] == "KOSPI"
    assert rows[0]["upcode"] == "001"

    bad = one + b"XX"
    try:
        codec.decode_occurs(block, bad)
    except ValueError:
        pass
    else:
        raise AssertionError("Malformed framing must fail")

    print("V38_2_REAL_CRLF_OCCURS_FRAMING_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
