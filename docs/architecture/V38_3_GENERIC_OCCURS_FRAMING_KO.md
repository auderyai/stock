# V38.3 generic OCCURS framing

실제 관찰:
- t8424 body = 23 bytes
- payload = 6300 bytes
- 6300 / 25 = 252 rows
- 실제 2-byte trailer는 CRLF라고 단정할 수 없음

정책:
- 특정 delimiter 값을 하드코딩하지 않는다.
- body+2 stride가 성립할 때 모든 2-byte trailer가 동일한지 검증한다.
- 동일하면 transport framing으로 제거한다.
- 다르면 오류 처리한다.
- schema field size는 변경하지 않는다.
