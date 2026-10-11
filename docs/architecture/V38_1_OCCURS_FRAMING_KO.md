# V38.1 OCCURS framing

문제:
`t8424OutBlock`의 RES body size는 23 bytes지만 실제 DLL payload는 6300 bytes였다.

관찰:
- 23 + CRLF(2) = 25 bytes
- 6300 / 25 = 252 rows

원칙:
TR별 예외를 만들지 않는다.

PacketCodec이 공통으로 아래 두 형태를 지원한다.
1. fixed-width compact: `[body][body]...`
2. DLL CRLF framed: `[body]\r\n[body]\r\n...`

RES/JSON schema의 field size는 변경하지 않는다.
CRLF는 전송 framing이며 schema field가 아니다.
