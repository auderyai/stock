# OpenDART 재무자료 연도별 백필 운영

## 고정 순서

실행 단위는 분기이고 완료 승인 단위는 연도다.

1. 2025년 Q1 → 반기 → Q3 → 사업보고서를 차례로 수집한다.
2. 각 100개 회사 배치를 DuckDB로 검증하고 임시 PostgreSQL에 저장한다.
3. 검증된 배치만 암호화하여 Google Drive에 체크포인트로 저장한다.
4. 2025년 네 보고서가 모두 완료된 뒤 로컬 PC에 반영한다.
5. 로컬 PostgreSQL의 0건·누락·멱등 검증이 끝난 뒤에만 2024년을 시작한다.
6. 같은 방식으로 2023년까지 진행한다.

GitHub Actions는 하루에 다음 미완료 보고서 하나를 실행한다. PC가 꺼져 있어도
클라우드 수집은 계속되지만 다음 연도는 직전 연도의 로컬 완료 확인을 기다린다.

## 비밀값

OpenDART 키는 코드, `.env`, 로그, manifest 및 Drive 파일명에 기록하지 않는다.
GitHub 저장소의 Actions secret `OPENDART_API_KEY`로만 공급한다. 기존 Drive 비밀값과
`DRIVE_ARCHIVE_KEY`도 동일하게 Actions secrets에서 공급한다.

## 로컬 반영

Drive에 해당 연도의 네 보고서가 모두 완료된 후 PowerShell에서 실행한다.

```powershell
$env:PYTHONPATH='src'
.venv_krx_menu\Scripts\python.exe scripts\opendart_financial_backfill.py `
  --years 2025,2024,2023 sync-local --year 2025
```

상태만 확인할 때는 다음 명령을 사용한다.

```powershell
$env:PYTHONPATH='src'
.venv_krx_menu\Scripts\python.exe scripts\opendart_financial_backfill.py `
  --years 2025,2024,2023 status
```

로컬 명령은 기존 `config/google_drive_oauth.dpapi`의 암호화된 Drive 자격증명을
재사용하며 OpenDART 키를 요구하지 않는다.
