# V35 최종 통일 기준

- PySide6 View → Controller → Service → Repository
- 화면 조회: PostgreSQL + SQL만 사용
- 화면에서 LS API 직접 호출 금지
- LS 외부 수집: xingAPI COM 단일화
- KOSPI200/KOSDAQ150 구성종목: xingAPI 갱신 → market_core.index_membership_snapshot → 화면 SQL 조회
- 종합·업종지수: xingAPI 갱신 → PostgreSQL → 화면 조회
- t1702 수급: xingAPI → PostgreSQL
- t8451 NXT/COMBINED: xingAPI → PostgreSQL
- OPEN API OAuth는 주 실행경로에서 제거
- root 최소화, 설정/도구/문서는 각 폴더 관리
