from __future__ import annotations
import tempfile
from pathlib import Path

from krx_research.database.settings import resolve_database_target


def check() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".env").write_text(
            "\\n".join([
                "KRX_DB_ENGINE=postgresql",
                "KRX_DB_HOST=127.0.0.1",
                "KRX_DB_PORT=5432",
                "KRX_DB_NAME=krx_research",
                "KRX_DB_USER=common_user",
                "KRX_DB_WRITE_PASSWORD=secret",
            ]) + "\\n",
            encoding="utf-8",
        )
        read = resolve_database_target(root, read_only=True)
        write = resolve_database_target(root, read_only=False)
        assert read.user == "common_user"
        assert read.password == "secret"
        assert write.user == "common_user"
        assert write.password == "secret"

        (root / ".env").write_text(
            "\\n".join([
                "KRX_DB_ENGINE=postgresql",
                "KRX_DB_HOST=127.0.0.1",
                "KRX_DB_NAME=krx_research",
                "KRX_DB_USER=common_user",
                "KRX_DB_WRITE_PASSWORD=write_secret",
                "KRX_DB_READ_USER=real_reader",
                "KRX_DB_READ_PASSWORD=read_secret",
            ]) + "\\n",
            encoding="utf-8",
        )
        read2 = resolve_database_target(root, read_only=True)
        assert read2.user == "real_reader"
        assert read2.password == "read_secret"

    print("V32_DB_CREDENTIAL_POLICY_CHECK: PASS")


if __name__ == "__main__":
    check()
