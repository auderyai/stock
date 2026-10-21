# 노트북 Stock 설치 및 남은 설정

PostgreSQL 18.6 병렬 설치·복원과 메뉴 시작 검증의 최신 결과는
[PostgreSQL 계정 설정 문서](POSTGRESQL_ACCOUNT_SETUP_KO.md)를 따른다.
아래 2026-10-21 기록은 DB 복원 전의 초기 설치 상태다.

## 설치 확인 (2026-10-21)

- Git 및 64비트 Python 3.11.9를 확인했다.
- `INSTALL_STOCK_LAPTOP.cmd`의 기존 저장소 감지를 `\.git\NUL`에서 `\.git`으로 수정했다.
  따옴표로 감싼 기존 NUL 경로는 이 Windows 환경에서 존재하는 저장소를 놓쳤다.
- 기존 설치기를 재실행해 `.venv_krx_menu`, `.venv_finplot`과 선언된 의존성을 설치했다.
- `.env`는 없을 때만 `.env.example`에서 생성하며, 기존 파일은 보존한다.
- 두 환경의 `pip check`, 메뉴/차트 모듈 가져오기와 Qt 초기화를 확인했다.
- 실제 메뉴 및 NextGen 진입점은 DB 비밀번호가 비어 있어 시작이 중단되었다.
  DB와 연동한 화면 시작 및 데이터 검증이 완료된 상태는 아니다.
- PostgreSQL 16 공식 EDB 설치기는 다운로드 및 해시 검증 후 대화형으로 실행했다.
  설치기는 `설치 성공`과 종료 코드 0으로 완료됐다.
  `postgres`, `pg_dump`, `pg_restore`의 버전은 모두 16.15로 확인했다.
  관리자 승인과 관리자 암호 입력은 사용자가 직접 처리했다.
  `postgresql-x64-16` 서비스는 Running / Automatic이며, 127.0.0.1:5432는
  `pg_isready`에서 accepting connections로 확인했다. Stock DB 복원 검증과는 별개다.
- OAuth JSON과 DPAPI 토큰은 없으며, 전용 도구의 JSON 사전 검증은 미완료로 판정했다.
- DB 복원, Drive 동기화/정리 작업 및 예약 작업 등록은 실행하지 않았다.

## PostgreSQL 설치 완료 후 확인

공식 안내: <https://www.postgresql.org/download/windows/>

설치 경로는 `C:\Program Files\PostgreSQL\16`, 포트는 다른 서비스와 충돌하지 않으면
5432를 사용한다. 관리자 암호는 설치 화면에 직접 입력하며 채팅·명령행·로그에 넣지 않는다.
Stack Builder 추가 구성 요소는 이 프로젝트의 기본 설치에 필요하지 않다.

다음 확인은 데이터 조회나 변경 없이 실행 파일과 서비스 준비 상태만 확인한다.

```powershell
Get-Service -Name '*postgres*'
& 'C:\Program Files\PostgreSQL\16\bin\postgres.exe' --version
& 'C:\Program Files\PostgreSQL\16\bin\pg_restore.exe' --version
& 'C:\Program Files\PostgreSQL\16\bin\pg_isready.exe' -h 127.0.0.1 -p 5432
```

서비스 실행이나 포트 응답만으로 Stock DB 복원 성공을 판정하지 않는다.

## 반드시 필요한 데스크톱 백업

검증된 최종 데스크톱 백업은 아직 제공되지 않았다. 빈 DB나 임시 재무자료로 대체하지 않는다.
노트북의 `C:\stock\POSTGRESQL_BACKUP`에 원본을 보존할 수 있도록 다음을 준비한다.

1. 데스크톱의 최종 검증된 Stock PostgreSQL 전체 백업. 프로젝트의
   `scripts\backup_local_store.py`가 사용하는 `pg_dump --format=custom` 형식의 `.dump`가 기준이다.
   PostgreSQL 16의 `pg_restore`로 읽을 수 있는 버전이어야 한다.
2. 전송 전후 무결성 확인용 SHA-256, 파일 크기, 백업 시각, 원본 PostgreSQL/pg_dump 버전,
   실제 DB 이름. 비밀번호와 자격증명은 백업 설명에 넣지 않는다.
3. 원본 검증 결과: 스키마/테이블 목록, 테이블별 행 수, 최신 거래일과 재무자료 기준일,
   완료 범위와 체크포인트. 0건 또는 누락을 완료로 처리하지 않는다.
4. 복원에 필요한 확장 기능, 소유자와 읽기/쓰기 역할 및 권한 정보.
   일반 pg_dump에는 클러스터 역할 자체가 포함되지 않으므로 별도 확인이 필요하다.
   역할 암호나 암호 해시를 채팅·Git에 올리지 않는다.

백업을 받으면 원본 해시를 먼저 대조하고, 공식 `pg_restore`의 목록 검사를 통과한 뒤
대상 DB·역할·복원 범위를 확정한다. 기존 노트북 DB에 덮어쓰거나 `--clean`으로 삭제하지 않는다.
스키마·행 수·최신 기준일·완료 범위·체크포인트를 데스크톱 결과와 대조하기 전까지 복원 성공이 아니다.

## 사용자가 직접 입력할 항목

`C:\stock\.env`를 로컬 편집기에서 열어 값만 입력한다. 이 파일을 채팅에 붙여넣거나
내용을 터미널에 출력하지 않는다. 기존 설치기는 재실행해도 파일을 덮어쓰지 않는다.

| 항목 | 입력 기준 |
|---|---|
| `KRX_DB_HOST`, `KRX_DB_PORT` | 설치한 노트북 PostgreSQL의 주소/포트. 기본 템플릿은 127.0.0.1 / 5432 |
| `KRX_DB_NAME` | 검증된 데스크톱 백업을 복원할 실제 DB 이름 |
| `KRX_DB_READ_USER`, `KRX_DB_READ_PASSWORD` | 복원 DB에 권한이 있는 실제 읽기 전용 계정과 암호 |
| `KRX_DB_WRITE_USER`, `KRX_DB_WRITE_PASSWORD` | 수집/동기화에 사용하는 실제 쓰기 계정과 암호 |
| `KRX_DB_DUMP` | `pg_dump`가 PATH에 없으면 `C:\Program Files\PostgreSQL\16\bin\pg_dump.exe`의 전체 경로 |
| `DART_API_KEY` | DART 기능을 사용할 때 발급받은 본인 키 |
| `GEMINI_API_KEY` | 해당 AI 기능을 사용할 때 발급받은 본인 키 |
| `LS_APP_KEY`, `LS_APP_SECRET` | LS 수집 기능용 본인 발급값. 기존 `scripts\setup_ls_openapi_credentials_once.py` 설정 도구 사용 가능 |

DB 계정은 설치 관리자의 postgres 계정으로 임의 대체하지 않는다. 백업의 역할/권한과 일치시킨다.
다른 API의 키나 OAuth 값을 DB 비밀번호 대신 넣지 않는다.

## Google Drive OAuth

1. 본인의 Google Cloud Desktop OAuth 클라이언트 JSON을 로컬의
   `C:\stock\tools\setup\google_oauth_client.json`에 준비한다. JSON 내용을 출력하거나 Git에 넣지 않는다.
2. `tools\setup\SETUP_GOOGLE_DRIVE_OAUTH_ONCE.cmd`를 실행해 본인이 브라우저 로그인과 Drive 권한 승인을 처리한다.
3. 기존 도구는 `drive.file` 범위로 전용 폴더를 확인하고 연결 시험 파일을 업로드/다운로드한 뒤
   그 시험 파일만 삭제한다. 완료된 업무 자료의 정리 작업은 아니다.
4. 토큰은 현재 Windows 사용자에 묶인 `config\google_drive_oauth.dpapi`로 암호화 저장한다.
   다른 PC의 DPAPI 토큰을 복사해서 사용하지 않는다.
5. 설정 후 `tools\setup\google_drive_oauth_once.py --verify-stored`로 연결을 확인한다.

`.env`, OAuth JSON과 DPAPI 파일의 Git 제외 규칙은 확인했다.
데스크톱/노트북 DB 검증 전 완료 자료 삭제나 정리 예약 작업을 등록하지 않는다.

## 실행 및 최종 검증

메뉴 실행: `C:\stock\tools\setup\LAUNCH_V42_KRX_MENU.cmd`

차트 실행: `C:\stock\nextgen\RUN_STAGE4_MAIN_WINDOW.cmd`

실제 DB 복원 및 자격증명 입력 후 두 프로그램을 다시 실행하고 읽기 전용으로 DB 검증을 진행해야 한다.
`INSTALL_STOCK_LAPTOP.cmd verify`는 DB/OAuth 확인에 더해 Drive 변경분 반영과 예약 작업 등록까지
수행하므로 단순 조회 검증으로 실행하지 않는다. 양쪽 DB 검증 전에는 사용하지 않는다.
