# new_stock 루트 보관 원칙

루트에는 실행/환경/패키징에 직접 필요한 항목만 둔다.

## 루트 유지
- .git, .venv
- .env, .env.example, .gitignore
- README.md, pyproject.toml, requirements*
- RUN_NEW_STOCK.cmd
- RUN_NEW_STOCK_NO_CONSOLE.cmd
- SETUP_NEW_STOCK_ENV.cmd
- VERIFY_NEW_STOCK.cmd
- config/, docs/, KRX_Menu_Launcher/, logs/, reports/, scripts/, src/, templates/, tools/

## 기능별 보관
- KRX_Menu_Launcher/: 메뉴 런처 관련 파일
- docs/: 아키텍처/분석/변경이력/구조 문서
- tools/: Git/설치/패치 보조도구
- reports/: 검증 및 생성 리포트
- logs/: 런타임 로그

사용자 제공 run_krx_menu(2).bat는 KRX_Menu_Launcher/run_krx_menu.bat로 관리한다.
