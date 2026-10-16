# Stock 저장소 필수 작업 규칙

이 파일은 `C:\stock` 아래의 모든 프로그램 작성·수정에 적용한다.

## 작업 전

1. `git status --short`로 사용자 변경과 작업 범위를 확인하고 관련 없는 파일을 보존한다.
2. `docs/engineering/ENGINEERING_PRINCIPLES_KO.md`와 변경 영역의 기존 Policy, Strategy,
   Presenter, Controller, Service, Repository를 먼저 확인한다.
3. 다음 명령으로 불변 원칙 목록을 확인한다.

```powershell
$env:PYTHONPATH='src'
.venv_krx_menu\Scripts\python.exe scripts\verify_engineering_principles.py before
```

## 구현

- 한 객체는 한 책임만 갖게 하고 View → Controller → Service → Repository 의존 방향을 지킨다.
- 기존 공통 객체를 확장하며 화면·실행 파일에 동일 규칙을 다시 구현하지 않는다.
- 중복, 임시방편, 우회 분기, 불필요한 추상화를 만들지 않고 전체 코드 길이를 최소화한다.
- DB는 조회가 기본이며 쓰기·삭제·외부 변경은 명시된 서비스와 검증 절차로만 수행한다.
- 사용자 변경, 비밀값, DB 원본, 완료 데이터와 체크포인트를 보존한다.
- 0건, 부분 누락, 검증 실패를 성공으로 처리하지 않는다.
- 결과표는 공통 표시·정렬 객체를, 차트는 공통 탐색 Strategy를 사용한다.

## 작업 후

1. 변경 동작의 정상·경계·회귀 테스트를 실행한다.
2. 다음 명령으로 아키텍처·UI·Git 안전 규칙을 확인한다.

```powershell
$env:PYTHONPATH='src'
.venv_krx_menu\Scripts\python.exe scripts\verify_engineering_principles.py after
```

3. `git diff --check`와 `git diff`를 검토하고 요청 범위 파일만 커밋한다.
4. 관련 없는 기존 변경은 수정·스테이징·커밋하지 않는다.

