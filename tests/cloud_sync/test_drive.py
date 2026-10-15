from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from krx_research.cloud_sync.drive import GoogleDriveClient


class GoogleDriveClientTests(unittest.TestCase):
    def test_request_refreshes_expired_access_token_once(self) -> None:
        session = MagicMock()
        initial_token = MagicMock(ok=True, status_code=200)
        initial_token.json.return_value = {"access_token": "initial"}
        refreshed_token = MagicMock(ok=True, status_code=200)
        refreshed_token.json.return_value = {"access_token": "refreshed"}
        session.post.side_effect = [initial_token, refreshed_token]

        expired = MagicMock(status_code=401)
        accepted = MagicMock(status_code=200)
        session.get.side_effect = [expired, accepted]

        client = GoogleDriveClient(
            client_id="id",
            client_secret="secret",
            refresh_token="refresh",
            root_folder_id="folder",
            session=session,
        )
        response = client._request("get", "https://example.test/files", timeout=30)

        self.assertIs(response, accepted)
        self.assertEqual(2, session.get.call_count)
        self.assertEqual(2, session.post.call_count)
        session.headers.update.assert_any_call({"Authorization": "Bearer refreshed"})

    def test_delete_requires_successful_drive_response(self) -> None:
        session = MagicMock()
        token = MagicMock(ok=True, status_code=200)
        token.json.return_value = {"access_token": "token"}
        session.post.return_value = token
        deleted = MagicMock(ok=True, status_code=204)
        session.delete.return_value = deleted
        client = GoogleDriveClient(
            client_id="id", client_secret="secret", refresh_token="refresh",
            root_folder_id="folder", session=session,
        )

        client.delete("file-id")

        session.delete.assert_called_once()

    def test_delete_is_idempotent_when_file_is_missing(self) -> None:
        session = MagicMock()
        token = MagicMock(ok=True, status_code=200)
        token.json.return_value = {"access_token": "token"}
        session.post.return_value = token
        session.delete.return_value = MagicMock(ok=False, status_code=404)
        client = GoogleDriveClient(
            client_id="id", client_secret="secret", refresh_token="refresh",
            root_folder_id="folder", session=session,
        )

        client.delete("missing")


if __name__ == "__main__":
    unittest.main()
