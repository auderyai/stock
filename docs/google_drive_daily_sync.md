# Google Drive 일일 PostgreSQL 변경분 동기화

## 구조

- GitHub Actions는 평일 20:37(Asia/Seoul)에 임시 PostgreSQL 18을 시작합니다.
- Google Drive의 암호화 작업 상태를 복원한 뒤 KRX 작업 메뉴 2, 5, 7을 순서대로 실행합니다.
- 메뉴 7은 메뉴 5를 중복 실행하지 않도록 `--no-investor`를 사용합니다.
- 성공한 경우에만 일일 변경분과 다음 작업 상태를 AES-256-GCM으로 암호화해 Drive에 올립니다.
- PC는 `sync-local`로 아직 반영하지 않은 변경분만 PostgreSQL `UPSERT`합니다.
- 적용 이력은 `market_core.drive_sync_batches`에 기록되어 재실행해도 중복 반영되지 않습니다.

Google Drive OAuth 범위는 `drive.file`이며 이 프로그램이 만든 파일에만 접근합니다. OAuth JSON,
refresh token, DB 비밀번호, LS API 비밀값과 암호화 키는 Git에 저장하지 않습니다.

## GitHub Actions Secrets

저장소의 `Settings > Secrets and variables > Actions`에 아래 이름을 등록합니다.

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `GOOGLE_DRIVE_FOLDER_ID`
- `DRIVE_ARCHIVE_KEY`
- `LS_APP_KEY`
- `LS_APP_SECRET`

Windows에서 값 자체를 화면에 출력하지 않고 하나씩 복사하려면 다음 명령을 사용합니다.

```powershell
.venv_krx_menu\Scripts\python.exe tools\setup\copy_github_secret.py GOOGLE_CLIENT_ID
```

마지막 인수만 위 Secret 이름으로 바꿉니다. 붙여넣은 뒤 클립보드는 다른 일반 텍스트를
복사해 지웁니다.

Git Credential Manager에 `auderyai/stock` 쓰기 자격증명이 이미 저장된 경우에는 값 자체를
출력하지 않고 GitHub 공개키로 암호화하여 7개를 한 번에 등록할 수 있습니다.

```powershell
.venv_krx_menu\Scripts\python.exe tools\setup\register_github_actions_secrets.py
```

## PC 반영

수동 실행:

```powershell
tools\setup\RUN_PC_DRIVE_SYNC.cmd
```

매일 07:00부터 23:00까지 1시간 간격으로 확인하고, PC가 꺼져 있어 놓친 경우 다음
Windows 로그인 후 실행하도록 등록:

```powershell
tools\setup\REGISTER_PC_DRIVE_SYNC_TASK.cmd
```

각 실행은 `market_core.drive_sync_batches`의 적용 이력을 먼저 확인합니다. 따라서 새 변경분이
없거나 같은 변경분을 이미 적용한 경우에는 DB에 중복 반영하지 않습니다.

감사 로그는 `logs/cloud_sync/drive_sync.log`에 성공·실패 상태만 기록하며 비밀값은 기록하지 않습니다.
