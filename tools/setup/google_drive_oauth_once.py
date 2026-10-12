from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[2]
CLIENT_PATH = ROOT / "tools" / "setup" / "google_oauth_client.json"
TOKEN_PATH = ROOT / "config" / "google_drive_oauth.dpapi"
LOG_PATH = ROOT / "logs" / "setup" / "google_drive_oauth_setup.log"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
ROOT_FOLDER_NAME = "stock-cloud"

sys.path.insert(0, str(ROOT / "src"))

from krx_research.infrastructure.windows_dpapi_store import (  # noqa: E402
    WindowsDpapiJsonStore,
)


class GoogleDriveSetupError(RuntimeError):
    """Safe setup error that never includes OAuth secrets or access tokens."""


class SafeAuditLog:
    """Append setup milestones only; credential values and HTTP bodies are forbidden."""

    def __init__(self, path: Path = LOG_PATH) -> None:
        self.path = path

    def write(self, event: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(f"{timestamp} {event}\n")


@dataclass(frozen=True)
class DesktopOAuthClient:
    client_id: str
    client_secret: str
    auth_uri: str
    token_uri: str

    @classmethod
    def load(cls, path: Path) -> "DesktopOAuthClient":
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            installed = document["installed"]
            client = cls(
                client_id=str(installed["client_id"]).strip(),
                client_secret=str(installed["client_secret"]).strip(),
                auth_uri=str(installed["auth_uri"]).strip(),
                token_uri=str(installed["token_uri"]).strip(),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GoogleDriveSetupError(
                "Desktop OAuth JSON 형식이 아니거나 파일을 읽을 수 없습니다."
            ) from exc
        if not all((client.client_id, client.client_secret, client.auth_uri, client.token_uri)):
            raise GoogleDriveSetupError("Desktop OAuth JSON에 필수 값이 없습니다.")
        if not client.client_id.endswith(".apps.googleusercontent.com"):
            raise GoogleDriveSetupError("Google Desktop OAuth client_id 형식이 아닙니다.")
        return client


class DriveApi:
    def __init__(self, access_token: str) -> None:
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {access_token}"})

    def ensure_root_folder(self) -> str:
        query = (
            f"name = '{ROOT_FOLDER_NAME}' and "
            "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        response = self._session.get(
            f"{DRIVE_API}/files",
            params={"q": query, "spaces": "drive", "fields": "files(id,name)"},
            timeout=30,
        )
        payload = self._json(response, "Drive 폴더 조회")
        files = payload.get("files", [])
        if files:
            return str(files[0]["id"])
        response = self._session.post(
            f"{DRIVE_API}/files",
            params={"fields": "id"},
            json={
                "name": ROOT_FOLDER_NAME,
                "mimeType": "application/vnd.google-apps.folder",
            },
            timeout=30,
        )
        return str(self._json(response, "Drive 폴더 생성")["id"])

    def verify_round_trip(self, folder_id: str) -> None:
        content = b"auderyai-stock Google Drive OAuth verification\n"
        response = self._session.post(
            f"{DRIVE_UPLOAD_API}/files",
            params={"uploadType": "multipart", "fields": "id"},
            files=(
                (
                    "metadata",
                    (
                        None,
                        json.dumps(
                            {
                                "name": ".oauth-connection-test.txt",
                                "parents": [folder_id],
                            }
                        ),
                        "application/json; charset=UTF-8",
                    ),
                ),
                ("file", ("oauth-test.txt", content, "text/plain")),
            ),
            timeout=60,
        )
        file_id = str(self._json(response, "시험 파일 업로드")["id"])
        try:
            downloaded = self._session.get(
                f"{DRIVE_API}/files/{file_id}", params={"alt": "media"}, timeout=30
            )
            self._require_success(downloaded, "시험 파일 다운로드")
            if downloaded.content != content:
                raise GoogleDriveSetupError("Drive 시험 파일 내용 검증에 실패했습니다.")
        finally:
            deleted = self._session.delete(f"{DRIVE_API}/files/{file_id}", timeout=30)
            self._require_success(deleted, "시험 파일 삭제")

    def verify_root_folder(self, folder_id: str) -> None:
        response = self._session.get(
            f"{DRIVE_API}/files/{folder_id}",
            params={"fields": "id,name,mimeType,trashed"},
            timeout=30,
        )
        payload = self._json(response, "Drive 전용 폴더 확인")
        if (
            payload.get("name") != ROOT_FOLDER_NAME
            or payload.get("mimeType") != "application/vnd.google-apps.folder"
            or payload.get("trashed") is True
        ):
            raise GoogleDriveSetupError("Drive 전용 폴더 상태가 올바르지 않습니다.")

    @classmethod
    def _json(cls, response: requests.Response, operation: str) -> dict[str, Any]:
        cls._require_success(response, operation)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleDriveSetupError(f"{operation} 응답 형식이 잘못되었습니다.") from exc
        if not isinstance(payload, dict):
            raise GoogleDriveSetupError(f"{operation} 응답 형식이 잘못되었습니다.")
        return payload

    @staticmethod
    def _require_success(response: requests.Response, operation: str) -> None:
        if not response.ok:
            raise GoogleDriveSetupError(
                f"{operation} 실패: HTTP {response.status_code}. Google Cloud 설정을 확인하십시오."
            )


class GoogleDriveOAuthSetup:
    def __init__(self, client_path: Path = CLIENT_PATH, token_path: Path = TOKEN_PATH):
        self._client_path = client_path
        self._token_store = WindowsDpapiJsonStore(token_path)

    def validate_client(self) -> DesktopOAuthClient:
        return DesktopOAuthClient.load(self._client_path)

    def run(self) -> Path:
        client = self.validate_client()
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise GoogleDriveSetupError(
                "Google OAuth 라이브러리가 없습니다. CMD 실행 파일로 다시 시작하십시오."
            ) from exc

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._client_path), scopes=[DRIVE_FILE_SCOPE]
        )
        credentials = flow.run_local_server(
            host="localhost",
            port=0,
            open_browser=True,
            authorization_prompt_message=(
                "브라우저에서 개인 Gmail 계정으로 로그인한 뒤 Google Drive 접근을 승인하십시오."
            ),
            success_message=(
                "Google Drive 승인이 완료되었습니다. 이 브라우저 창을 닫아도 됩니다."
            ),
            access_type="offline",
            prompt="consent",
        )
        if not credentials.refresh_token or not credentials.token:
            raise GoogleDriveSetupError("장기 실행에 필요한 OAuth 토큰을 받지 못했습니다.")

        drive = DriveApi(credentials.token)
        folder_id = drive.ensure_root_folder()
        drive.verify_round_trip(folder_id)
        self._token_store.save(
            {
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "refresh_token": credentials.refresh_token,
                "token_uri": client.token_uri,
                "scope": DRIVE_FILE_SCOPE,
                "root_folder_id": folder_id,
            }
        )
        return self._token_store.path

    def verify_stored(self) -> None:
        try:
            document = self._token_store.load()
            required = (
                "client_id",
                "client_secret",
                "refresh_token",
                "token_uri",
                "scope",
                "root_folder_id",
            )
            if any(not str(document.get(name, "")).strip() for name in required):
                raise GoogleDriveSetupError("암호화 자격증명에 필수 값이 없습니다.")
            if document["scope"] != DRIVE_FILE_SCOPE:
                raise GoogleDriveSetupError("저장된 Google Drive 권한 범위가 다릅니다.")
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials

            credentials = Credentials(
                token=None,
                refresh_token=document["refresh_token"],
                token_uri=document["token_uri"],
                client_id=document["client_id"],
                client_secret=document["client_secret"],
                scopes=[DRIVE_FILE_SCOPE],
            )
            credentials.refresh(Request())
            DriveApi(credentials.token).verify_root_folder(document["root_folder_id"])
        except GoogleDriveSetupError:
            raise
        except Exception as exc:
            raise GoogleDriveSetupError(
                "저장된 OAuth 자격증명으로 Drive 연결을 확인하지 못했습니다."
            ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="개인 Google Drive OAuth 1회 설정")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--validate-only", action="store_true", help="비밀값 출력 없이 JSON 형식만 검사"
    )
    mode.add_argument(
        "--verify-stored", action="store_true", help="암호화 저장된 토큰과 Drive 폴더 확인"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup = GoogleDriveOAuthSetup()
    audit = SafeAuditLog()
    try:
        if args.verify_stored:
            audit.write("VERIFY_START")
            setup.verify_stored()
            audit.write("VERIFY_SUCCESS drive_folder=stock-cloud")
            print("저장된 Google Drive OAuth 및 stock-cloud 폴더: VALID")
            print(f"보안 로그: {audit.path}")
            return 0
        setup.validate_client()
        if args.validate_only:
            print("Desktop OAuth JSON: VALID")
            return 0
        audit.write("SETUP_START")
        audit.write("CLIENT_JSON_VALID")
        print("OAuth JSON 검증 완료. 브라우저 승인을 시작합니다.")
        path = setup.run()
        audit.write("SETUP_SUCCESS drive_folder=stock-cloud token_store=DPAPI")
        print(f"Google Drive 연결 검증 완료. 암호화 자격증명: {path}")
        print(f"Drive 전용 폴더 생성/확인 완료: {ROOT_FOLDER_NAME}")
        print(f"보안 로그: {audit.path}")
        return 0
    except GoogleDriveSetupError as exc:
        audit.write(f"FAILED error={type(exc).__name__}")
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        audit.write(f"FAILED error={type(exc).__name__}")
        print(f"[ERROR] {type(exc).__name__}: 설정을 완료하지 못했습니다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
