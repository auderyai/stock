# V37.3 DLL runtime gate

확정 사항:

- `C:\LS_SEC\xingAPI_Program(2025.06.07)\XingAPI.dll` 존재
- 32bit Python에서 필수 ETK export PASS
- 최신 설치본 `Header`에는 ChartExcel.h / ChartIndex.h만 존재
- 최신 설치본 `Res`에는 TR RES가 없음

따라서 transport와 packet schema를 분리한다.

`transport_ready`
- 32bit Python 존재
- XingAPI.dll 존재

`runtime_ready`
- transport_ready
- t8424/t8436/t1516/t8429/t8451/t1702 schema 모두 검증 완료

schema가 하나라도 없으면 메뉴 2/5/7을 DLL runtime으로 전환하지 않는다.
