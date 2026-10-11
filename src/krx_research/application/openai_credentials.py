from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

import requests

from krx_research.infrastructure.windows_dpapi_store import WindowsDpapiJsonStore


@dataclass(frozen=True, slots=True)
class OpenAICredentials:
    api_key: str
    model: str


class OpenAICredentialResolver:
    """Resolve process credentials first, then the current-user DPAPI store."""

    FILE_NAME = "openai_credentials.dpapi"

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve()
        self.store = WindowsDpapiJsonStore(self.root / "config" / self.FILE_NAME)

    def load(self) -> OpenAICredentials | None:
        key = os.getenv("OPENAI_API_KEY", "").strip()
        model = os.getenv("OPENAI_MODEL", "").strip()
        if key:
            return OpenAICredentials(key, model or "gpt-5.4")
        if not self.store.path.is_file():
            return None
        document = self.store.load()
        key = str(document.get("api_key") or "").strip()
        model = str(document.get("model") or "gpt-5.4").strip()
        if not key:
            raise RuntimeError("암호화된 OpenAI API 키가 비어 있습니다.")
        return OpenAICredentials(key, model)


class OpenAICredentialRegistrationService:
    """Validate without logging a key, then persist it with Windows DPAPI."""

    _MODEL = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

    def __init__(self, project_root: str | Path, *, session=None):
        self.resolver = OpenAICredentialResolver(project_root)
        self.session = session or requests.Session()

    def register(self, api_key: str, model: str) -> Path:
        key, selected_model = api_key.strip(), model.strip()
        if not key or any(character.isspace() for character in key):
            raise ValueError("공백 없는 OpenAI API 키를 입력하십시오.")
        if not self._MODEL.fullmatch(selected_model):
            raise ValueError("모델 이름 형식이 잘못되었습니다.")
        response = self.session.get(
            f"https://api.openai.com/v1/models/{selected_model}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        if response.status_code == 401:
            raise RuntimeError("OpenAI API 키 인증에 실패했습니다.")
        if response.status_code == 403:
            raise RuntimeError("OpenAI API 키에 모델 조회 권한이 없습니다.")
        if response.status_code == 404:
            raise RuntimeError("입력한 OpenAI 모델을 사용할 수 없습니다.")
        if not response.ok:
            raise RuntimeError(f"OpenAI 연결 확인에 실패했습니다({response.status_code}).")
        self.resolver.store.save({"api_key": key, "model": selected_model})
        stored = self.resolver.store.load()
        if stored.get("api_key") != key or stored.get("model") != selected_model:
            raise RuntimeError("암호화 저장 검증에 실패했습니다.")
        return self.resolver.store.path
