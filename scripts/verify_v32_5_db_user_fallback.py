from pathlib import Path
import tempfile
from krx_research.database.settings import resolve_database_target

def check():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".env").write_text(
            "\n".join([
                "KRX_DB_ENGINE=postgresql",
                "KRX_DB_HOST=127.0.0.1",
                "KRX_DB_PORT=5432",
                "KRX_DB_NAME=krx_research",
                "KRX_DB_WRITE_PASSWORD=existing_secret",
            ]) + "\n",
            encoding="utf-8",
        )
        read = resolve_database_target(root, read_only=True)
        write = resolve_database_target(root, read_only=False)
        assert read.user == "krx_writer"
        assert write.user == "krx_writer"
        assert read.password == "existing_secret"
        assert write.password == "existing_secret"

        (root / ".env").write_text(
            "\n".join([
                "KRX_DB_ENGINE=postgresql",
                "KRX_DB_HOST=127.0.0.1",
                "KRX_DB_NAME=krx_research",
                "KRX_DB_USER=custom_user",
                "KRX_DB_WRITE_PASSWORD=existing_secret",
            ]) + "\n",
            encoding="utf-8",
        )
        custom = resolve_database_target(root, read_only=True)
        assert custom.user == "custom_user"

    print("V32_5_DB_USER_FALLBACK_CHECK: PASS")

if __name__ == "__main__":
    check()
