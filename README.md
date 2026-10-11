# KRX Research NextGen

PyQt6 + Finplot/PyQtGraph + PostgreSQL 전용 KRX workstation입니다.

## 설치/적용
1. `C:\stock`에서 작업합니다.
2. NextGen 환경은 `C:\stock\.venv_finplot`을 사용합니다.
3. `VERIFY_NEW_STOCK.cmd`로 PyQt6/Finplot/PostgreSQL을 검증한 후 `RUN_NEW_STOCK.cmd`를 실행합니다.

## 데이터베이스
- PostgreSQL만 사용합니다.
- 기본 자격정보는 `C:\stock\.env`를 재사용합니다.
- new_stock 폴더 안에 별도 SQLite DB를 만들지 않습니다.

## V5 핵심
- 결과표/세부표 한글 표시
- 원시 SQL/traceback 화면 노출 방지
- 종목명/종목코드 검색
- 이동평균 유사배열 기준 종목 선택 필수
- 결과 목록과 차트 연동
- PySide6 + FigureCanvasQTAgg
- 고전전략 및 보조지표 시나리오 UI 보강
- Application/Controller/Service/View/Presenter/Worker 계층 분리

자세한 내용은 `ORIGINAL_ZIP_ANALYSIS_KO.md`, `ARCHITECTURE_OOP_KO.md`, `CHANGELOG_KO.md`를 참조하십시오.

## V6 차트 결과목록 동작
- `결과목록 탐색 · 같은 차트 갱신`을 체크한 상태에서 차트를 열면 차트 오른쪽에 현재 조회 결과가 붙습니다.
- 오른쪽 결과목록에서 행을 클릭하거나 키보드 `↑/↓`로 이동하면 같은 차트 창의 종목이 즉시 바뀝니다.
- 체크하지 않은 경우에는 선택한 한 종목의 차트만 새 창으로 열립니다. 오른쪽 결과목록은 표시하지 않습니다.
- 모든 PySide6 결과표에는 공통 표시정책이 적용됩니다: 순위/종목코드 가운데 정렬, 거래량 천단위 쉼표와 오른쪽 정렬, 중복 거래일 숨김, 원 단위 거래대금/자료출처 숨김.

### V7 수급 표시 규칙
- `시가 총액` 한글 헤더 사용
- `구분`: `순매수` / `순매도`
- `순매매대금(억원)`: 억원, 소수점 1자리, 천단위 쉼표, 순매도는 `-` 부호 유지
- 수급 Top10 내부 컬럼 `screen_type`, `score`는 화면에 표시하지 않음
- 수급 대시보드 최초 실행은 메인 조회조건의 시작/종료일을 검증해 전달하며, 이후에는 수급 화면 자체 기간으로 조회

## Git 사용 (V10부터 기본)
`C:\stock`만 Git 관리 대상으로 사용합니다. PostgreSQL 실제 데이터와 비밀정보는 Git에 넣지 않습니다.

최초 1회:
```bat
GIT_SETUP_NEW_STOCK.cmd
```

일상 작업:
```bat
GIT_STATUS.cmd
GIT_CHECKPOINT.cmd
GIT_COMMIT.cmd
GIT_LOG.cmd
```

패치 적용 시 기존 `.git` 폴더는 보존됩니다. 기존 Git 저장소에 미커밋 변경사항이 있으면 패치 복사 전에 checkpoint commit을 먼저 생성합니다.

원격 저장소를 사용할 경우:
```bat
GIT_REMOTE_SET.cmd
GIT_PUSH.cmd
```

## 보조지표 시나리오 (V11)

차트의 `보조지표 시나리오·AI`는 원본 workstation 방식으로 동작합니다. 보조지표 목표값과 도달 기간을 입력하면 과거 일봉의 시간순 학습/검증, KOSPI/KOSDAQ 지수 컨텍스트(가능한 경우), 목표 지표값에 맞는 가상 OHLCV 경로 및 전체 보조지표 변화를 계산합니다. GUI는 PySide6만 사용하며 DB 조회는 PostgreSQL SQL Repository 계층을 통합니다.

### V12 종합·업종 지수
- 메인 `결과목록 탐색 · 같은 차트 갱신` 체크 상태를 종합·업종 지수 창에도 그대로 적용합니다.
- 체크됨: 오른쪽 종합/업종 목록 + 클릭/↑↓로 같은 차트 즉시 갱신.
- 체크 안 됨: 상단 지수 선택 콤보 변경 즉시 단일 차트 갱신.
- PostgreSQL/SQL 접근은 `MarketIndexRepository` 한 곳으로 제한합니다.


## V13
보조지표 시나리오 표 정렬, 자유 학습기간 입력, Bollinger σ 축 라벨 제거를 PySide6/OOP 공통 정책으로 적용했습니다.

## V17 점수 중복 제거
- 모든 PySide6 결과표에서 `점수(score)` 컬럼을 전역 제거합니다.
- 52주 신고가/상승률/주간/볼린저/EMA 유사배열/수급 등에서 기존 지표를 복사하던 `score` 생성을 제거했습니다.
- 의미 있는 원본 지표(`일간(%)`, `주간(%)`, `배열 유사도(%)`, `52주 신고가 대비(%)`, `순매매대금(억원)`)는 그대로 유지합니다.
- 과거 PostgreSQL 테이블의 `score` 컬럼은 DB 호환성을 위해 스키마에만 남기되 UI/Excel에는 노출하지 않습니다.
- 보조지표 시나리오 내부 최적화의 로컬 `score`는 실제 목적함수이므로 유지합니다.

### V19 순위 입력
메인 조회조건의 `출력 순위`에 원하는 숫자를 입력하면 해당 순위만큼 출력한다. 수급 대시보드도 동일한 공통 순위 입력 위젯을 사용한다. 주간 거래대금 스크리너 3종이 추가되었다.

## V20 주간 상승률 Top-N
- KOSPI 주간 상승률 Top 50
- KOSDAQ 주간 상승률 Top 50
- KOSPI+KOSDAQ 주간 상승률 Top 50
- 메인 `출력 순위`에 입력한 N만큼 실제 결과를 표시하며 제목의 Top N도 함께 갱신됩니다.

### V24 LS 설정
LS OPEN API 실키는 Git에 넣지 않고 `C:\stock\.env`의 `LS_APP_KEY`, `LS_APP_SECRET`을 사용합니다.
