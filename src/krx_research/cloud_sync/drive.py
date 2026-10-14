from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests


TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"


class GoogleDriveError(RuntimeError):
    pass


class GoogleDriveClient:
    """Minimal drive.file client for files created by the stock automation."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        root_folder_id: str,
        session: requests.Session | None = None,
    ) -> None:
        values = (client_id, client_secret, refresh_token, root_folder_id)
        if any(not str(value).strip() for value in values):
            raise GoogleDriveError("Google Drive OAuth 환경값이 모두 필요합니다.")
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self.root_folder_id = root_folder_id
        self._session = session or requests.Session()
        self._authenticate()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "GoogleDriveClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def ensure_folder(self, name: str, parent_id: str | None = None) -> str:
        parent = parent_id or self.root_folder_id
        found = self.find(name, parent)
        if found:
            return str(found["id"])
        response = self._request(
            "post",
            f"{DRIVE_API}/files",
            params={"fields": "id"},
            json={
                "name": name,
                "parents": [parent],
                "mimeType": "application/vnd.google-apps.folder",
            },
            timeout=30,
        )
        return str(self._json(response, "Drive 폴더 생성")["id"])

    def find(self, name: str, parent_id: str) -> dict[str, Any] | None:
        escaped = name.replace("'", "\\'")
        response = self._request(
            "get",
            f"{DRIVE_API}/files",
            params={
                "q": f"name = '{escaped}' and '{parent_id}' in parents and trashed = false",
                "spaces": "drive",
                "fields": "files(id,name,mimeType,md5Checksum,size,modifiedTime)",
                "pageSize": 10,
            },
            timeout=30,
        )
        files = self._json(response, "Drive 파일 조회").get("files", [])
        return dict(files[0]) if files else None

    def list_folder(self, parent_id: str) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {
                "q": f"'{parent_id}' in parents and trashed = false",
                "spaces": "drive",
                "fields": "nextPageToken,files(id,name,mimeType,md5Checksum,size,modifiedTime)",
                "pageSize": 1000,
            }
            if page_token:
                params["pageToken"] = page_token
            response = self._request(
                "get", f"{DRIVE_API}/files", params=params, timeout=30
            )
            payload = self._json(response, "Drive 폴더 목록 조회")
            files.extend(dict(item) for item in payload.get("files", []))
            page_token = str(payload.get("nextPageToken") or "") or None
            if page_token is None:
                return files

    def upload(self, source: Path, *, name: str, parent_id: str) -> str:
        existing = self.find(name, parent_id)
        file_id = str(existing["id"]) if existing else None
        endpoint = (
            f"{DRIVE_UPLOAD_API}/files/{file_id}"
            if file_id
            else f"{DRIVE_UPLOAD_API}/files"
        )
        metadata: dict[str, Any] = {"name": name}
        if not file_id:
            metadata["parents"] = [parent_id]
        initiated = self._request(
            "patch" if file_id else "post",
            endpoint,
            params={"uploadType": "resumable", "fields": "id,size,md5Checksum"},
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "application/octet-stream",
                "X-Upload-Content-Length": str(source.stat().st_size),
            },
            json=metadata,
            timeout=30,
        )
        self._require_success(initiated, "Drive 업로드 세션 생성")
        upload_url = initiated.headers.get("Location")
        if not upload_url:
            raise GoogleDriveError("Drive 업로드 세션 주소가 없습니다.")
        with source.open("rb") as stream:
            uploaded = self._session.put(
                upload_url,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(source.stat().st_size),
                },
                data=stream,
                timeout=900,
            )
        payload = self._json(uploaded, "Drive 파일 업로드")
        if int(payload.get("size", -1)) != source.stat().st_size:
            raise GoogleDriveError("Drive 업로드 파일 크기가 일치하지 않습니다.")
        return str(payload["id"])

    def download(self, file_id: str, target: Path) -> Path:
        response = self._request(
            "get",
            f"{DRIVE_API}/files/{file_id}", params={"alt": "media"}, stream=True, timeout=900
        )
        self._require_success(response, "Drive 파일 다운로드")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("wb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    stream.write(chunk)
        temporary.replace(target)
        return target

    def read_json(self, name: str, parent_id: str) -> dict[str, Any] | None:
        found = self.find(name, parent_id)
        if not found:
            return None
        response = self._request(
            "get",
            f"{DRIVE_API}/files/{found['id']}", params={"alt": "media"}, timeout=30
        )
        payload = self._json(response, "Drive JSON 다운로드")
        return payload

    def write_json(self, document: dict[str, Any], *, name: str, parent_id: str) -> str:
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            temporary = Path(stream.name)
        try:
            return self.upload(temporary, name=name, parent_id=parent_id)
        finally:
            temporary.unlink(missing_ok=True)

    def _authenticate(self) -> None:
        response = self._session.post(
            TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        token = str(self._json(response, "Google OAuth 토큰 갱신").get("access_token") or "")
        if not token:
            raise GoogleDriveError("Google OAuth 접근 토큰이 없습니다.")
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Retry one Drive request after refreshing an expired access token."""
        response = getattr(self._session, method)(url, **kwargs)
        if response.status_code == 401:
            self._authenticate()
            response = getattr(self._session, method)(url, **kwargs)
        return response

    @classmethod
    def _json(cls, response: requests.Response, operation: str) -> dict[str, Any]:
        cls._require_success(response, operation)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleDriveError(f"{operation} 응답이 JSON이 아닙니다.") from exc
        if not isinstance(payload, dict):
            raise GoogleDriveError(f"{operation} 응답 형식이 잘못되었습니다.")
        return payload

    @staticmethod
    def _require_success(response: requests.Response, operation: str) -> None:
        if not response.ok:
            raise GoogleDriveError(f"{operation} 실패: HTTP {response.status_code}")
