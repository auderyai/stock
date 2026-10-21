# 노트북 PostgreSQL 계정 설정

## PostgreSQL 18.6 복원 검증 결과 (2026-10-22)

- PostgreSQL 18.6을 별도 서비스와 5433 포트에 설치했다. PostgreSQL 16:5432는 보존했다.
- 지정한 백업의 2,452,148,830바이트·SHA-256 및 18.6 `pg_restore --list` 검사를 통과했다.
- 원본 데이터 67개 항목, 총 55,239,409행을 복원했다. 파티션 부모를 포함한 68개 테이블 건수와
  최신 거래일 2026-10-21, 재무자료 2026년 반기, 체크포인트를 원본과 대조했다.
- 읽기·쓰기 계정, 소유자 로그인 제한, DB·스키마·테이블·시퀀스 최소 권한을 검증한 뒤 `.env`를
  5433으로 전환했다. `setup_postgresql.py`와 `--verify-accounts`가 모두 PASS다.
- 실제 V42 메뉴가 표시되고 이벤트 루프에 진입했다. 해당 실행의 시작 예외는 없었다.
- 백업 원본부터 0건인 데이터 항목 16개와 파티션 부모도 그대로 보존했다.
  해당 투자자 정규화 자료·재무 주석 등의 수집을 완료로 처리하지 않는다.
- 테이블별 건수·재무·체크포인트 상세 보고서:
  `C:\stock\logs\restore\pg18_20261021_235053_173013\validation_completed.json`.
  초기 검증 중단 보고서도 같은 폴더에 보존했다. 백업·기존 DB·Drive 자료는 삭제하지 않았다.

## PostgreSQL 16 초기 검증 결과 (2026-10-21)

- `krx_research`의 읽기·쓰기 계정 설정 및 `.env` 반영을 완료했다.
- `setup_postgresql.py`: `POSTGRESQL_CONNECTION: PASS`.
- `setup_postgresql.py --verify-accounts`: 두 계정의 실제 인증, 최소 권한,
  소유자 로그인 제한, 기본 테이블 권한, 업무 테이블이 없는 상태를 확인했다.
- `.env`의 Windows 접근 권한 상속은 차단되었으며 현재 사용자와 SYSTEM의 두 접근 규칙만 사용한다.
- 최종 데스크톱 백업은 복원하지 않았다. 업무 자료나 시험 테이블을 생성하지 않았다.

## 실행 방법

로컬 PostgreSQL 16의 빈 `krx_research` DB를 설정하는 정식 진입점:

```powershell
& C:\stock\.venv_krx_menu\Scripts\python.exe C:\stock\scripts\setup_postgresql.py --configure
```

비밀번호는 로컬 창에서만 입력한다. 설치 때 정한 `postgres` 관리자 암호와 서로 다른
읽기/쓰기 계정 암호를 입력하고 확인한다. 관리자 암호는 저장하지 않는다.
쓰기 계정이 아직 없어도 된다. 새 `krx_writer` 암호를 직접 정하면 이 도구가 계정을 생성한다.
API 키는 PostgreSQL 계정 암호로 사용하지 않는다.
암호를 인수·환경 변수·대화·로그에 넣지 않는다.

- `krx_owner`: 로그인 불가 소유자. DB/역할 생성 및 관리자 권한 없음.
- `krx_reader`: CONNECT, 스키마 USAGE, 테이블 SELECT. 기본 읽기 전용.
- `krx_writer`: CONNECT, 스키마 USAGE, 테이블 SELECT/INSERT/UPDATE/DELETE,
  시퀀스 USAGE/SELECT. DB·스키마·임시 테이블 생성 권한 없음.
- 두 로그인 계정은 슈퍼유저·CREATEDB·CREATEROLE·복제·BYPASSRLS·다른 역할 멤버십이 없다.
- 새 업무 테이블은 만들지 않는다. 소유자와 postgres가 향후 생성하는 객체의 기본 권한만
  대상 DB 안에서 설정한다. 데스크톱 백업과 업무 자료는 복원하지 않는다.

기존 동명 DB/역할을 무조건 인수하지 않는다. 이 도구가 만든 대상인지 확인하고,
기존 업무 테이블이 있으면 암호를 변경하기 전에 중단한다.
새 DB 생성은 PostgreSQL 제약에 따라 역할 트랜잭션과 분리되며, 중간 실패 시 만들어진
관리 대상 역할/빈 DB는 삭제하지 않고 재실행한다.

비밀번호는 클라이언트에서 SCRAM으로 변환한 뒤 역할에 설정한다. 관리자 연결의 세션에서
SQL·매개변수·오류 SQL 로깅을 억제하고, 상세 드라이버 예외를 화면/로그로 전달하지 않는다.
두 계정의 실제 인증과 권한 확인 후 공통 `EnvFileRepository`가 네 자격증명 항목과 로컬 DB
주소를 `.env`에 반영한다. 관련 없는 항목은 보존하고, Windows 파일 접근 권한은 현재 사용자와
SYSTEM으로 제한한다. `.env`는 Git에 넣지 않는다.

연결 확인:

```powershell
& C:\stock\.venv_krx_menu\Scripts\python.exe C:\stock\scripts\setup_postgresql.py
& C:\stock\.venv_krx_menu\Scripts\python.exe C:\stock\scripts\setup_postgresql.py --verify-accounts
```

두 번째 명령은 저장된 두 계정의 인증·최소 권한·기본 테이블 권한을 검사한다.
5432의 초기 설정에서는 빈 DB를, 5433에서는 복원 테이블의 읽기·쓰기 권한을 확인한다.
이 명령만으로 백업 건수와 자료 기준일까지 검증한 것은 아니다.

## PostgreSQL 18.6 병렬 복원

PostgreSQL 16:5432는 보존한다. 공식 설치기로 PostgreSQL 18.6 서버와 명령줄 도구를
별도 경로 `C:\Program Files\PostgreSQL\18`, 포트 5433, 서비스 `postgresql-x64-18`에 설치한다.
기존 설정 진입점의 다음 모드는 로컬 숨김 입력창에서 18의 관리자 암호만 받는다.
읽기·쓰기 암호는 현재 `.env`에서 재사용하며 관리자 암호는 저장하지 않는다.

```powershell
& C:\stock\.venv_krx_menu\Scripts\python.exe C:\stock\scripts\setup_postgresql.py `
  --migrate-to-18 `
  --backup C:\stock\POSTGRESQL_BACKUP\krx_research_20261021_220421.dump `
  --expected-size 2452148830 `
  --sha256 877EC8349A025B1834B77C2BAFFE0136AE63795068586A5A5736014403A77E2C `
  --latest-trade-date 2026-10-21
```

정확한 크기·SHA-256 및 18.6 `pg_restore --list`를 먼저 확인한다. 백업 행은 출력하거나
별도 원본 파일로 저장하지 않고 스트림에서 테이블 건수·날짜·재무 분기·체크포인트 상태를 집계한다.
검증 후 5433의 관리 대상 빈 DB에만 최소 권한 계정을 설정하고, `krx_owner`로 단일 트랜잭션 복원한다.
`--clean`이나 기존 DB 삭제는 사용하지 않는다. 복원 후 실제 테이블 건수와 집계 기준을 비교하고
계정별 권한을 검증한 뒤에만 `.env`의 포트와 `pg_dump` 경로를 18로 전환한다.

안전한 집계 결과는 `C:\stock\logs\restore\pg18_*\validation.json`에 남긴다.
실패하면 실패 단계와 SQLSTATE 또는 비밀값을 제외한 오류만 보고하고 자료를 보존한다.
복원된 DB가 비어 있지 않으면 다시 덮어쓰지 않는다. PostgreSQL 16 제거는 별도 승인 대상이다.

복원 후에는 같은 진입점의 `--verify-restored <validation.json의 절대 경로>`로
기존 보고서의 원본 집계와 실제 DB를 읽기 전용으로 다시 대조할 수 있다.
파티션 부모의 건수도 백업 자식 테이블 건수 합계와 비교한다.
`--inspect-backup`은 위의 백업·크기·해시·기준일 인수와 함께 사용하며 DB 변경 없이 백업만 검사한다.

복원 트랜잭션은 성공했으나 `restored-validation` 단계에서 중단된 경우에는
`--verify-restored <실패 보고서> --complete-18 --latest-trade-date 2026-10-21`로
기존 DB를 다시 복원하지 않고 읽기 전용 검증부터 재개한다. 모든 검증 통과 후에만 `.env`를
5433으로 전환하며, 기존 실패 보고서는 보존하고 `validation_completed.json`을 별도로 기록한다.
