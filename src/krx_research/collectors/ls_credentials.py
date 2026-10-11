"""LS OpenAPI credential resolution shared by index membership and LS collectors."""
from __future__ import annotations

import os
from pathlib import Path


class LSCredentialError(RuntimeError):
    pass


class LSCredentialResolver:
    KEY_ALIASES = (
        "LS_APP_KEY",
        "LS_OPENAPI_APP_KEY",
        "LS_OPEN_API_APP_KEY",
        "LS_OPENAPI_KEY",
        "LS_OPEN_API_KEY",
        "XING_APP_KEY",
        "XING_OPENAPI_APP_KEY",
    )
    SECRET_ALIASES = (
        "LS_APP_SECRET",
        "LS_OPENAPI_APP_SECRET",
        "LS_OPEN_API_APP_SECRET",
        "LS_OPENAPI_SECRET",
        "LS_OPEN_API_SECRET",
        "XING_APP_SECRET",
        "XING_OPENAPI_APP_SECRET",
    )

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).expanduser().resolve()

    @staticmethod
    def _read_env(path: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        if not path.is_file():
            return values
        text = path.read_text(encoding="utf-8-sig")
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
        return values

    def candidate_files(self) -> tuple[Path, ...]:
        return (
            self.project_root / ".env",
            self.project_root / "config" / "ls_openapi.env",
        )

    def values(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for path in self.candidate_files():
            merged.update(self._read_env(path))
        merged.update({k: v for k, v in os.environ.items() if v is not None})
        return merged

    @classmethod
    def _first(cls, values: dict[str, str], aliases: tuple[str, ...]) -> str:
        for name in aliases:
            value = values.get(name)
            if value and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _normalized(name: str) -> str:
        return "".join(ch for ch in name.upper() if ch.isalnum())

    @classmethod
    def _heuristic(cls, values: dict[str, str], *, secret: bool) -> str:
        token = "SECRET" if secret else "KEY"
        for name, value in values.items():
            normalized = cls._normalized(name)
            if not value or not value.strip():
                continue
            if not ("LS" in normalized or "XING" in normalized):
                continue
            if token not in normalized:
                continue
            if secret and ("APPSECRET" in normalized or "OPENAPISECRET" in normalized):
                return value.strip()
            if not secret and ("APPKEY" in normalized or "OPENAPIKEY" in normalized):
                return value.strip()
        return ""

    def load(self) -> tuple[str, str]:
        values = self.values()
        key = self._first(values, self.KEY_ALIASES) or self._heuristic(values, secret=False)
        secret = self._first(values, self.SECRET_ALIASES) or self._heuristic(values, secret=True)

        if key and secret:
            return key, secret

        visible_names = sorted(
            name for name in values
            if ("LS" in name.upper() or "XING" in name.upper())
            and ("KEY" in name.upper() or "SECRET" in name.upper())
        )
        locations = "\n".join(
            f" - {path} ({'존재' if path.is_file() else '파일 없음'})"
            for path in self.candidate_files()
        )
        names = ", ".join(visible_names) if visible_names else "없음"
        raise LSCredentialError(
            "LS OPEN API 자격증명을 찾지 못했습니다.\n"
            "지원 키 이름: LS_APP_KEY / LS_APP_SECRET 및 LS_OPENAPI/XING 호환 이름\n"
            f"발견된 LS/XING 환경변수 이름: {names}\n"
            "확인 위치:\n" + locations
        )


def load_ls_credentials(project_root: str | Path) -> tuple[str, str]:
    return LSCredentialResolver(project_root).load()
