# V38.4 DLL wire layout

실제 관찰:
- t8424OutBlock DevCenter/RES size = 23 bytes
- fields = 2
- live DLL packet = 6300 bytes
- 6300 / 252 = 25 bytes/row
- 25 = 23 + 2 fields

따라서 transport-level `+2` delimiter가 아니라,
DLL output이 각 fixed-width field 뒤에 C-string NUL 1 byte를 포함하는
wire representation인지 검증한다.

공통 PacketCodec 지원:
1. packed: declared field widths only
2. field-NUL: each declared field followed by `\x00`

schema의 field size는 변경하지 않는다.
