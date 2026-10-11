# V38.5 RES Attribute wire rule

확정 근거:
- DevCenter t8424/t8436/t8429/t8451/t1516/t1702 화면: Attribute = O
- live t8424: schema body 23, fields 2, packet 6300
- 23 + fields(2) = 25, 6300 / 25 = 252
- live 오류에서 hname 직후 byte = 0x20
- LS DLL reference parser: attr이면 record_size에 field count를 더하고,
  각 field를 읽은 뒤 pointer를 1 byte 추가 이동

정책:
- schema field size는 declared size만 보관
- BlockSchema.is_attr를 명시
- wire_size = schema body + field_count (attr일 때)
- input attr byte는 ASCII space
- output attr byte 값은 데이터로 해석하지 않고 skip
- RES와 JSON 이후에는 동일 PacketCodec 사용
