from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principle:
    code: str
    title: str
    mandate: str


@dataclass(frozen=True, slots=True)
class EngineeringPolicy:
    """Immutable, executable catalog for every Stock code change."""

    principles: tuple[Principle, ...]

    def text(self) -> str:
        return "\n".join(f"[{item.code}] {item.title}: {item.mandate}" for item in self.principles)

    def require(self, *codes: str) -> tuple[Principle, ...]:
        selected = tuple(item for item in self.principles if item.code in codes)
        missing = set(codes) - {item.code for item in selected}
        if missing:
            raise KeyError(", ".join(sorted(missing)))
        return selected


DEFAULT_ENGINEERING_POLICY = EngineeringPolicy((
    Principle("ARCH-1", "객체 책임", "한 객체 한 책임과 View→Controller→Service→Repository 방향을 지킨다."),
    Principle("ARCH-2", "공통 객체", "기존 Policy·Strategy·Presenter를 먼저 찾아 규칙 중복을 금지한다."),
    Principle("LEAN-1", "코드 극소화", "중복·임시방편·우회 분기·불필요한 추상화를 만들지 않는다."),
    Principle("DATA-1", "자료 보존", "사용자 변경·DB 원본·완료 데이터·체크포인트를 보존한다."),
    Principle("SEC-1", "비밀 보호", "비밀값·자격증명·DB 원본을 출력하거나 커밋하지 않는다."),
    Principle("DB-1", "DB 경계", "조회는 읽기 전용이며 쓰기·삭제는 전용 서비스로만 수행한다."),
    Principle("RUN-1", "멱등 재개", "0건·누락을 성공 처리하지 않고 완료 다음 위치부터 재개한다."),
    Principle("UI-1", "표시·정렬", "공통 표 정책과 기능 Presenter로 열·형식·숫자 정렬을 강제한다."),
    Principle("CHART-1", "차트 연동", "공통 Strategy에 선택 종목과 정렬된 전체 결과를 전달한다."),
    Principle("CLOUD-1", "클라우드 단계", "메뉴 2 없이 메뉴 5 완료 검증 후 메뉴 7만 실행한다."),
    Principle("DELETE-1", "안전 삭제", "검증·계획·명시적 확인·메타데이터 정리를 모두 요구한다."),
    Principle("TEST-1", "검증", "관련 테스트·컴파일·정적 검사·diff 검사를 통과한다."),
    Principle("GIT-1", "변경 격리", "요청 범위만 커밋하고 관련 없는 사용자 변경을 보존한다."),
))

