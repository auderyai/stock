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

    row = b"KOSPI               " + b"001"
    assert len(row) == 23

    # Compact.
    assert len(codec.decode_occurs(block, row * 3)) == 3

    # CRLF is accepted, but no longer special-cased.
    framed_crlf = (row + b"\r\n") * 252
    assert len(framed_crlf) == 6300
    assert len(codec.decode_occurs(block, framed_crlf)) == 252

    # Any constant 2-byte DLL framing is accepted.
    framed_nul = (row + b"\x00\x00") * 252
    assert len(framed_nul) == 6300
    assert len(codec.decode_occurs(block, framed_nul)) == 252

    diag = codec.framing_diagnostic(block, framed_nul)
    assert diag["framed_divisible"] is True
    assert diag["trailer_constant"] is True
    assert diag["trailer_hex"] == "0000"

    # Variable trailers are rejected.
    bad = (row + b"\x00\x00") + (row + b"\x01\x00")
    try:
        codec.decode_occurs(block, bad)
    except ValueError:
        pass
    else:
        raise AssertionError("Non-constant framing must fail")

    print("V38_3_GENERIC_OCCURS_FRAMING_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
