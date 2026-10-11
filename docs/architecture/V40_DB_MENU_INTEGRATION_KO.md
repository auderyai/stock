# V40 DB·메뉴 통합

## 동결 계층
V39에서 실서버 PASS한 DLL/Schema/PacketCodec/Bridge는 변경하지 않는다.

`XingAPI.dll -> 32bit Worker -> XingDllSession -> TrSchema/PacketCodec -> XingBridgeClient`

## 메뉴 계층
- 메뉴 2: 기존 `run_daily_pipeline.py --until-complete --no-investor --markets KOSPI KOSDAQ` 유지 + V40 `t8424/t8436/t1516/t8429` PostgreSQL 통합
- 메뉴 5: `update_ls_investor_date_range.py` -> `XingDbMenuService.run_menu5()` -> `t1702` 원본/체크포인트 UPSERT
- 메뉴 7: `run_daily_integrated.py --ls-supplement` -> `XingDbMenuService.run_menu7()` -> `t8451` NXT/COMBINED 일봉 + `t1702` 수급 보완

## 객체지향 경계
`PySide6 Menu/Launcher -> script entry -> Application Service -> Port -> PostgreSQL Repository / XingBridgeClient`

Application 계층에는 PySide6, psycopg, ctypes, DLL 직접 호출을 넣지 않는다.

## DB 안전 원칙
- PostgreSQL만 사용한다.
- UPSERT/transaction으로 재실행 안전성을 유지한다.
- t1702는 4개 matrix(metric 0/1 x side 1/2)가 모두 있을 때만 해당 거래일 checkpoint를 완료 처리한다.
- SPAC은 LS 종목 마스터/지수 구성종목 저장에서 제외한다.
- 당일 확정 DB write는 20:10 이전 차단한다. 과거 날짜 backfill은 허용한다.
- t8451 거래대금은 기존 프로젝트 규칙대로 원시 `value`에 1,000,000을 곱해 canonical venue table에 저장한다.

## LS 전용 보조 테이블
`market_core.ls_sector_master`
`market_core.ls_security_master`
`market_core.ls_index_membership_raw`
`market_core.ls_sector_ohlcv_daily`
`market_core.ls_investor_t1702_raw`
`market_core.ls_investor_t1702_checkpoint`

canonical 주가/venue 테이블은 기존 `BaseDataRepository`가 계속 소유한다.

## 메뉴 2 직접호출 호환
설치기는 설치 직전 기존 `scripts/run_daily_pipeline.py`를 `scripts/run_daily_pipeline_v39_core.py`로 보존한다.
새 `run_daily_pipeline.py`는 기존 core에 모든 인자를 그대로 전달하고, core가 성공한 경우에만 메뉴 2 LS DB 단계를 실행한다.
따라서 기존 KRX 수집 로직은 재작성하거나 복제하지 않는다.


## V40.1 installer verifier fix
- Active runtime files only are checked for Qt binding imports.
- Qt checks use Python AST imports instead of raw substring matching.
- Historical verifier/migration scripts do not block V40 installation.
- V40 application layer still rejects direct psycopg/PySide6/Xing DLL/infrastructure imports.
