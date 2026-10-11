# V39 LS DLL 런타임 전체 자격검증

## 고정 원칙
- V38.5 RES attribute wire fix는 기준선으로 보존한다.
- PySide6 View는 LS DLL을 직접 호출하지 않는다.
- View -> Application Service -> XingBridgeClient -> 32bit Worker -> XingDllSession 순서를 지킨다.
- RES/JSON 모두 TrSchema -> PacketCodec 한 경로를 사용한다.
- PostgreSQL 저장 로직은 런타임 자격검증과 분리한다.

## 전체 검증 순서
1. DLL worker/login
2. t8424 업종 마스터
3. t8436 종목 마스터
4. t8429 업종 일봉
5. t8451 종목 일봉
6. t1516 지수 구성종목
7. t1702 투자주체 원본

`t8424/t8436` 응답에서 실제 업종/종목 코드를 얻어 후속 TR 입력으로 재사용한다.
따라서 테스트 전용 종목코드를 UI에 하드코딩하지 않는다.

## 완료 판정
6개 TR 모두 최소 1행 이상이며 대표 필수필드가 decode되어야 READY이다.
한 개라도 실패하면 NOT READY이며 DB write나 메뉴 통합을 진행하지 않는다.

## GUI 계층
`RuntimeWindow(View) -> RuntimeController -> RuntimeWorker(QThread) -> XingRuntimeQualificationService -> XingBridgeClient`.
View는 worker/DLL을 직접 호출하지 않는다.
