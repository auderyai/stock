from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing_schema import (
    JsonSchemaLoader,
    PacketCodec,
    ResSchemaLoader,
    TrSchemaService,
)


SAMPLE_RES = """BEGIN_FUNCTION_MAP

.Func,테스트(TEST),TEST,attr,headtype=A;

BEGIN_DATA_MAP

TESTInBlock,기본입력,input;
begin
구분,gubun,gubun,char,1;
요청건수,qrycnt,qrycnt,long,4;
end

TESTOutBlock,출력,output,occurs;
begin
종목명,hname,hname,char,20;
현재가,price,price,long,8;
등락률,diff,diff,float,6.2;
end

END_DATA_MAP
END_FUNCTION_MAP
"""


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "TEST.res"
        p.write_text(SAMPLE_RES, encoding="cp949")
        schema = ResSchemaLoader().load(p)

        assert schema.tr_code == "TEST"
        assert schema.input_blocks[0].size == 5
        assert schema.output_blocks[0].size == 34
        assert schema.output_blocks[0].occurs is True

        codec = PacketCodec()
        encoded = codec.encode(schema.input_blocks[0], {"gubun": "1", "qrycnt": 25})
        assert len(encoded) == 5
        assert encoded == b"1  25"

        decoded = codec.decode_one(
            schema.output_blocks[0],
            b"ABC                 " + b"   12345" + b" 12.34",
        )
        assert decoded["hname"] == "ABC"
        assert decoded["price"] == 12345
        assert str(decoded["diff"]) == "12.34"

    # Validate the current project JSON schemas when present.
    schema_dir = ROOT / "resources" / "xing" / "schemas"
    for tr in ("t1516", "t1702"):
        path = schema_dir / f"{tr}.json"
        if path.is_file():
            schema = JsonSchemaLoader().load(path)
            assert schema.tr_code == tr
            for block in schema.blocks:
                assert block.size == sum(f.size for f in block.fields)

    print("V37_7_UNIFIED_SCHEMA_CORE_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
