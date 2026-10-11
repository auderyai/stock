from __future__ import annotations

import os
import tempfile
from pathlib import Path

from krx_research.database.settings import resolve_database_target
from krx_research.environment import EnvironmentResolver


def _check_local_runtime_paths(root: Path) -> None:
    archive_paths = root / "src" / "krx_research" / "archive" / "paths.py"
    error_log_service = root / "src" / "krx_research" / "qt" / "services" / "error_log_service.py"

    if archive_paths.is_file():
        text = archive_paths.read_text(encoding="utf-8")
        assert 'project_root / "logs"' in text or "project_root/'logs'" in text or 'self.project_root / "logs"' in text

    if error_log_service.is_file():
        text = error_log_service.read_text(encoding="utf-8")
        assert "new_stock_error.log" in text
        assert '"logs"' in text or "'logs'" in text


def _check_db_behavior() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        project = base / "new_stock"
        project.mkdir()
        shared = base / "shared.env"

        shared.write_text(
            "\n".join(
                [
                    "KRX_DB_ENGINE=postgresql",
                    "KRX_DB_HOST=127.0.0.1",
                    "KRX_DB_PORT=5432",
                    "KRX_DB_NAME=krx_research",
                    "KRX_DB_WRITE_PASSWORD=existing-password",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        (project / ".env").write_text(
            "\n".join(
                [
                    "LS_APP_KEY=test-key",
                    "LS_APP_SECRET=test-secret",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        keys = ("KRX_SHARED_ENV", "KRX_DB_USER", "KRX_DB_READ_USER", "KRX_DB_READ_PASSWORD")
        previous = {key: os.environ.get(key) for key in keys}
        try:
            os.environ["KRX_SHARED_ENV"] = str(shared)
            for key in ("KRX_DB_USER", "KRX_DB_READ_USER", "KRX_DB_READ_PASSWORD"):
                os.environ.pop(key, None)

            values = EnvironmentResolver(project).values()
            assert values["KRX_DB_WRITE_PASSWORD"] == "existing-password"
            assert values["LS_APP_KEY"] == "test-key"

            read = resolve_database_target(project, read_only=True)
            write = resolve_database_target(project, read_only=False)

            assert read.user == "krx_writer"
            assert write.user == "krx_writer"
            assert read.password == "existing-password"
            assert write.password == "existing-password"
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _check_deprecated_read_tools_removed(root: Path) -> None:
    deprecated = [
        root / "SETUP_DB_READ_CREDENTIALS_ONCE.cmd",
        root / "scripts" / "setup_db_read_credentials_once.py",
        root / "scripts" / "check_repair_db_read_credentials.py",
        root / "tools" / "setup" / "CHECK_REPAIR_DB_READ_CREDENTIALS.cmd",
    ]
    present = [str(path.relative_to(root)) for path in deprecated if path.exists()]
    assert not present, "Deprecated READ credential tools remain: " + ", ".join(present)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    _check_local_runtime_paths(root)
    _check_db_behavior()
    _check_deprecated_read_tools_removed(root)
    print("V29_LOCAL_RUNTIME_PATHS_CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
