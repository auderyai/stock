# 유지보수 실행기

일상 프로그램 실행과 분리하여 일회성 복구·동기화·정리 도구만 보관한다.

- `RECOVER_NEW_LISTING_OHLCV_ONCE.cmd`: 신규 상장주 누락 일봉 일회성 복구
- `UPDATE_STOCK_FROM_GOOGLE_DRIVE.cmd`: 검증된 Drive 자료를 로컬 DB에 반영
- `CLEANUP_SYNCED_GOOGLE_DRIVE.cmd`: 로컬 반영·검증이 끝난 Drive 자료 정리

모든 실행기는 자신의 위치와 관계없이 저장소 루트를 계산하며, 비밀값을 표시하거나 변경하지 않는다.
