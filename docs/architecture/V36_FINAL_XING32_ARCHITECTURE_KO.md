# V36 최종 구조

- PySide6 메인: Python 64bit
- 화면: Controller -> Service -> Repository -> PostgreSQL SQL
- xingAPI: `.venv_xing32` Python 32bit worker 전용
- 메인 64bit에서 XA_Session/XAQuery 직접 생성 금지
- `XingBridgeClient`가 JSON-lines IPC로 32bit worker와 통신
- worker는 한 작업 동안 로그인 세션을 유지하므로 TR마다 재로그인하지 않음
- SQLite 금지
- root 최소화

대상 TR: t8424, t1516, t8429, t8451, t1702, t8436.
