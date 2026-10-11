# new_stock Git 작업 규칙

## 관리 대상
- 저장소: `C:\stock`
- 추적: `src`, `scripts`, `config`, `templates`, 검증/실행 스크립트, 문서
- 제외: `.venv`, `.env`, 로그, 캐시, 압축파일, 로컬 DB 파일
- PostgreSQL 실제 데이터와 비밀정보는 추적하지 않음

## 권장 흐름
1. 작업 시작: `GIT_STATUS.cmd`
2. 큰 변경 전: `GIT_CHECKPOINT.cmd`
3. 검증: `VERIFY_NEW_STOCK.cmd`
4. 실행 확인: `RUN_NEW_STOCK.cmd`
5. 완료 저장: `GIT_COMMIT.cmd`

## 원칙
- `.git` 폴더는 패치에 포함하거나 덮어쓰지 않음.
- 패치 전 기존 변경사항은 checkpoint commit으로 보존.
- 비밀번호/접속정보가 들어갈 수 있는 `.env`는 커밋 금지.
- PostgreSQL 데이터 디렉터리/덤프를 소스 저장소에 넣지 않음.

## 원격 저장소(GitHub 등)
원격 저장소를 사용할 때만 실행:
1. `GIT_REMOTE_SET.cmd`에서 origin URL 입력
2. `GIT_PUSH.cmd`로 main 브랜치 push

인증 정보/토큰은 파일에 저장하지 않으며 Git Credential Manager 또는 GitHub 인증 방식을 사용합니다.
