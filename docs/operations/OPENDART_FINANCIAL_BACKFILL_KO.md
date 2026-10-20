# OpenDART 재무자료 연도별 백필 운영

## 고정 순서

실행 단위는 분기이고 완료 승인 단위는 현재 수집 가능한 기간 또는 완료 연도다.

1. 2026년 10월 현재 제출이 끝난 Q1 → 반기를 먼저 수집한다.
2. 각 100개 회사 배치를 DuckDB로 검증하고 임시 PostgreSQL에 저장한다.
3. 검증된 배치만 암호화하여 Google Drive에 체크포인트로 저장한다.
4. 클라우드는 로컬 PC 상태와 관계없이 2026년 가용분 → 2025 → 2024 → 2023년을 연속 수집한다.
5. 로컬 PC가 켜지면 완료된 분기를 PostgreSQL에 멱등 반영한다.
6. 로컬 PostgreSQL의 기대·실제 행 수가 정확히 일치한 배치만 명시적 확인 후 Drive에서 삭제할 수 있다.
7. 이후 2026년 Q3 등 새 기간이 제출되면 기존 체크포인트 뒤에 추가한다.

GitHub Actions는 30분마다 다음 미완료 보고서를 확인한다. 동시 실행은 막되 진행 중 실행
뒤에 다음 실행이 대기하므로, PC가 꺼져 있거나 로컬 반영 전이어도 3개년 수집은 계속된다.

## 비밀값

OpenDART 키는 코드, `.env`, 로그, manifest 및 Drive 파일명에 기록하지 않는다.
GitHub 저장소의 Actions secret `OPENDART_API_KEY`로만 공급한다. 기존 Drive 비밀값과
`DRIVE_ARCHIVE_KEY`도 동일하게 Actions secrets에서 공급한다.

## 로컬 반영

Drive에 해당 연도의 현재 수집 대상 보고서가 모두 완료된 후 PowerShell에서 실행한다.

```powershell
$env:PYTHONPATH='src'
.venv_krx_menu\Scripts\python.exe scripts\opendart_financial_backfill.py `
  --years 2026,2025,2024,2023 sync-local --year 2026 `
  --cleanup-confirm DELETE_VERIFIED_FINANCIAL_ARCHIVES
```

상태만 확인할 때는 다음 명령을 사용한다.

```powershell
$env:PYTHONPATH='src'
.venv_krx_menu\Scripts\python.exe scripts\opendart_financial_backfill.py `
  --years 2026,2025,2024,2023 status
```

완료된 다음 연도가 있는지 확인하고 있을 때만 반영하려면 다음 명령을 사용한다.

```powershell
$env:PYTHONPATH='src'
.venv_krx_menu\Scripts\python.exe scripts\opendart_financial_backfill.py `
  --years 2026,2025,2024,2023 sync-ready-local `
  --cleanup-confirm DELETE_VERIFIED_FINANCIAL_ARCHIVES
```

`tools\setup\INSTALL_OPENDART_FINANCIAL_SYNC_ON_LOGON.cmd`를 한 번 실행하면 현재 사용자의
Windows 로그인 때 위 검사를 숨김 실행한다. 실행 기록은
`logs\financial_backfill\startup_sync.log`에 남는다. 클라우드의 4개 보고 기간이 모두
완료되지 않은 연도는 내려받거나 DB에 쓰지 않는다. 삭제 확인 문자열은 설치된 자동화에
명시되어 있으며, 로컬 멱등 재검증이 끝나기 전에는 삭제 단계에 도달하지 않는다.

로컬 반영이 끝나도 기대 행 수와 실제 행 수가 다르거나 일부 배치가 미반영이면 Drive
파일을 삭제하지 않는다. 완전 반영이 확인된 파일만 하나씩 삭제하고 매번 체크포인트를
갱신하므로, 삭제 도중 오류가 나면 다음 로그인에서 남은 파일부터 다시 정리한다. 삭제된
배치의 행 수와 완료 이력은 메타데이터에 보존한다.

로컬 명령은 기존 `config/google_drive_oauth.dpapi`의 암호화된 Drive 자격증명을
재사용하며 OpenDART 키를 요구하지 않는다.
