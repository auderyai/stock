from __future__ import annotations

from pathlib import Path
import requests

from krx_research.collectors.ls_credentials import LSCredentialResolver
from krx_research.infrastructure.env_file_repository import EnvFileRepository


class LSOpenApiCredentialService:
    TOKEN_URL = "https://openapi.ls-sec.co.kr:8080/oauth2/token"

    def __init__(self, project_root: str | Path, session=None) -> None:
        self.root = Path(project_root).resolve()
        self.repository = EnvFileRepository(self.root / ".env")
        self.session = session or requests.Session()

    def register(self, app_key: str, app_secret: str) -> None:
        key, secret = app_key.strip(), app_secret.strip()
        if not key or not secret: raise ValueError("APP KEY와 APP SECRET을 모두 입력하십시오.")
        response = self.session.post(self.TOKEN_URL, data={
            "grant_type": "client_credentials", "appkey": key,
            "appsecretkey": secret, "scope": "oob",
        }, timeout=15)
        response.raise_for_status()
        if not str(response.json().get("access_token") or "").strip():
            raise RuntimeError("LS OpenAPI 응답에 access_token이 없습니다.")
        self.repository.save({"LS_APP_KEY": key, "LS_APP_SECRET": secret})
        LSCredentialResolver(self.root).load()
