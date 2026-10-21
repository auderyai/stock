from pathlib import Path

from tools.setup.google_drive_oauth_once import (
    DEFAULT_AUTH_URI,
    DesktopOAuthClient,
    GoogleDriveOAuthSetup,
)


class _StoredCredentials:
    def load(self):
        return {
            "client_id": "desktop.apps.googleusercontent.com",
            "client_secret": "secret",
            "token_uri": "https://oauth2.googleapis.com/token",
        }


def test_setup_reuses_encrypted_client_when_downloaded_json_is_absent(tmp_path: Path):
    setup = GoogleDriveOAuthSetup(client_path=tmp_path / "missing.json")
    setup._token_store = _StoredCredentials()

    client = setup.validate_client()

    assert client.client_id == "desktop.apps.googleusercontent.com"
    assert client.auth_uri == DEFAULT_AUTH_URI


def test_client_flow_config_is_an_installed_application():
    client = DesktopOAuthClient(
        client_id="desktop.apps.googleusercontent.com",
        client_secret="secret",
        auth_uri=DEFAULT_AUTH_URI,
        token_uri="https://oauth2.googleapis.com/token",
    )

    assert client.flow_config() == {
        "installed": {
            "client_id": "desktop.apps.googleusercontent.com",
            "client_secret": "secret",
            "auth_uri": DEFAULT_AUTH_URI,
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
