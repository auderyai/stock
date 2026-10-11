# workstation_5900x-main(2).zip 재분석 요약

- Python 파일: 169개(src/scripts/tests 기준)
- 테스트 파일: 23개
- Tkinter/FigureCanvasTkAgg 사용 파일: 10개
- PySide6/FigureCanvasQTAgg 사용 파일: 4개(병행 전환 preview 포함)
- SQLite 관련 코드/설정이 다수 남아 있었고 MariaDB/PyMySQL 호환 코드도 존재했습니다.
- 원본 `ui/workstation.py`는 2천 줄 이상 규모의 단일 대형 GUI 클래스이며 UI, 비동기 실행, 차트, 내보내기, 탐색 책임이 집중되어 있었습니다.
- 원본 이동평균 유사배열 엔진 자체는 `comparison_ticker`를 이미 지원하지만 GUI에서 사용자가 기준 종목을 명확히 찾아 선택하는 흐름이 부족했습니다.
- 원본 결과표는 내부 컬럼을 직접 노출하지 않고 `기준일/순위/종목코드/종목명/업종/종가/일간(%)/주간(%)/거래대금(억원)` 같은 한글 헤더와 포맷을 사용했습니다.
- 원본 차트에는 고전전략 판정, 보조지표 표시 선택, 동일 차트 갱신, 보조지표 시나리오 기능이 포함되어 있었습니다.

V5는 위 기능을 PySide6 계층 구조로 옮기되 PostgreSQL 전용 정책을 유지합니다.
