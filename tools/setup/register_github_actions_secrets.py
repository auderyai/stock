from __future__ import annotations

import argparse
import base64
from pathlib import Path
import subprocess
import sys

import requests
from nacl.public import PublicKey, SealedBox


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "auderyai/stock"
API = f"https://api.github.com/repos/{REPOSITORY}/actions/secrets"
sys.path.insert(0, str(ROOT / "src"))

from krx_research.cloud_sync.credentials import DriveCredentials
from krx_research.collectors.ls_credentials import load_ls_credentials


class SecretRegistrationError(RuntimeError):
    pass


def _github_token() -> str:
    completed = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True,
        check=False,
    )
    values = dict(
        line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line
    )
    token = values.get("password", "").strip()
    if completed.returncode or not token:
        raise SecretRegistrationError("GitHub Git 자격증명을 찾지 못했습니다.")
    return token


def _verify_remote() -> None:
    completed = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    normalized = completed.stdout.strip().lower().removesuffix(".git")
    if completed.returncode or not normalized.endswith(f"github.com/{REPOSITORY}".lower()):
        raise SecretRegistrationError("Git 원격 저장소가 auderyai/stock이 아닙니다.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DPAPI 자격증명을 GitHub Actions Secrets에 암호화 등록"
    )
    parser.add_argument(
        "--drive-only",
        action="store_true",
        help="Google Drive 관련 비밀값만 갱신",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _verify_remote()
    drive = DriveCredentials.from_windows_store(
        ROOT / "config" / "google_drive_oauth.dpapi"
    )
    values = {
        "GOOGLE_CLIENT_ID": drive.client_id,
        "GOOGLE_CLIENT_SECRET": drive.client_secret,
        "GOOGLE_REFRESH_TOKEN": drive.refresh_token,
        "GOOGLE_DRIVE_FOLDER_ID": drive.root_folder_id,
        "DRIVE_ARCHIVE_KEY": drive.archive_key,
    }
    if not args.drive_only:
        ls_key, ls_secret = load_ls_credentials(ROOT)
        values.update({"LS_APP_KEY": ls_key, "LS_APP_SECRET": ls_secret})
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {_github_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    key_response = session.get(f"{API}/public-key", timeout=30)
    if not key_response.ok:
        raise SecretRegistrationError(
            f"GitHub 공개키 조회 실패: HTTP {key_response.status_code}"
        )
    document = key_response.json()
    public_key = PublicKey(base64.b64decode(document["key"]))
    box = SealedBox(public_key)
    for name, value in values.items():
        encrypted = base64.b64encode(box.encrypt(value.encode("utf-8"))).decode("ascii")
        response = session.put(
            f"{API}/{name}",
            json={"encrypted_value": encrypted, "key_id": document["key_id"]},
            timeout=30,
        )
        if response.status_code not in (201, 204):
            raise SecretRegistrationError(
                f"GitHub Secret 등록 실패: {name}, HTTP {response.status_code}"
            )
        print(f"REGISTERED {name}")
    print(f"GitHub Actions Secrets 등록 완료: {len(values)}개")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SecretRegistrationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
