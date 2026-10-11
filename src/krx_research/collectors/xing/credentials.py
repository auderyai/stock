from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from krx_research.environment import EnvironmentResolver
except ImportError:  # pragma: no cover - compatibility before V33
    EnvironmentResolver = None  # type: ignore


class XingCredentialError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class XingCredentials:
    user_id: str
    password: str
    cert_password: str = ""


class XingCredentialResolver:
    """Resolve xingAPI COM login credentials; never expose secret values."""

    USER_KEYS = ("LS_XING_ID", "XING_ID", "LS_USER_ID")
    PASSWORD_KEYS = ("LS_XING_PASSWORD", "XING_PASSWORD", "LS_PASSWORD")
    CERT_KEYS = ("LS_XING_CERT_PASSWORD", "XING_CERT_PASSWORD", "LS_CERT_PASSWORD")

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).expanduser().resolve()

    def _values(self) -> dict[str, str]:
        if EnvironmentResolver is not None:
            return EnvironmentResolver(self.project_root).values()
        values: dict[str, str] = {}
        for path in (self.project_root/".env",):
            if not path.is_file(): continue
            for raw in path.read_text(encoding="utf-8-sig").splitlines():
                line=raw.strip()
                if not line or line.startswith("#") or "=" not in line: continue
                key,value=line.split("=",1); values[key.strip()]=value.strip().strip('"').strip("'")
        return values

    @staticmethod
    def _first(values: dict[str, str], keys: tuple[str, ...]) -> str:
        for key in keys:
            value=values.get(key,"").strip()
            if value: return value
        return ""

    def load(self) -> XingCredentials:
        values=self._values()
        user=self._first(values,self.USER_KEYS)
        password=self._first(values,self.PASSWORD_KEYS)
        cert=self._first(values,self.CERT_KEYS)
        if not user or not password:
            raise XingCredentialError(
                "LS xingAPI 로그인 정보가 없습니다. tools/setup/SETUP_XINGAPI_CREDENTIALS_ONCE.cmd를 실행하십시오. "
                "필수 항목은 LS_XING_ID, LS_XING_PASSWORD입니다."
            )
        return XingCredentials(user,password,cert)
