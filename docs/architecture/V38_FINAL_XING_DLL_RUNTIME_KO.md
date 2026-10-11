# V38 최종 xingAPI 실행 구조

## 단일 실행 경로

PySide6 64bit
-> 기존 Controller/Service
-> `XingBridgeClient`
-> 32bit `.venv_xing32`
-> `XingDllSession`
-> `XingAPI.dll`
-> ETK_Request
-> `TrSchema`
-> `PacketCodec`
-> 기존 Repository/PostgreSQL

## Schema

- t8424/t8436/t8429/t8451: 관리 RES를 `ResSchemaLoader`가 읽음
- t1516/t1702: 최신 DevCenter 기반 JSON을 `JsonSchemaLoader`가 읽음
- 두 loader 이후에는 동일한 `TrSchema`와 `PacketCodec`만 사용

## 메뉴 통일

- 메뉴 2의 KOSPI200/KOSDAQ150 구성종목: t8424 + t1516 -> DLL worker
- 메뉴 5의 LS 수급 원본: t1702 -> DLL worker
- 메뉴 7의 일봉·수급 보완: t8451 + t1702 -> DLL worker
- 업종 지수: t8429 -> 동일 DLL worker

COM/XAQuery는 위 경로에서 사용하지 않는다.
