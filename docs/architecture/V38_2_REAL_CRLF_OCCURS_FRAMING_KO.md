# V38.2 REAL CRLF OCCURS framing

실제 t8424OutBlock body size는 23 bytes이고 DLL payload는 6300 bytes였다.

23 + CRLF(2) = 25
6300 / 25 = 252 rows

PacketCodec은 모든 OCCURS TR에 대해 다음 두 framing을 공통 지원한다.

1. `[body][body]...`
2. `[body]\r\n[body]\r\n...`

CRLF는 field schema가 아니라 DLL transport framing이므로 schema size는 변경하지 않는다.
