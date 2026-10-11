from __future__ import annotations
from pathlib import Path
import shutil


READ_KEYS = {"KRX_DB_READ_USER", "KRX_DB_READ_PASSWORD"}


class EnvReadCredentialCleaner:
    def __init__(self, env_path: Path) -> None:
        self.env_path = env_path

    def run(self) -> None:
        if not self.env_path.exists():
            return
        lines = self.env_path.read_text(encoding="utf-8").splitlines()
        kept = []
        for line in lines:
            stripped = line.strip()
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in READ_KEYS:
                    continue
            kept.append(line)
        self.env_path.write_text("\\n".join(kept).rstrip() + "\\n", encoding="utf-8")


class DeprecatedReadToolCleaner:
    def __init__(self, root: Path) -> None:
        self.root = root

    def run(self) -> None:
        obsolete = [
            self.root / "SETUP_DB_READ_CREDENTIALS_ONCE.cmd",
            self.root / "scripts" / "setup_db_read_credentials_once.py",
            self.root / "scripts" / "check_repair_db_read_credentials.py",
            self.root / "tools" / "setup" / "CHECK_REPAIR_DB_READ_CREDENTIALS.cmd",
        ]
        for path in obsolete:
            if path.is_file():
                path.unlink()


def main(root: Path) -> int:
    EnvReadCredentialCleaner(root / ".env").run()
    DeprecatedReadToolCleaner(root).run()
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(Path(sys.argv[1]).expanduser().resolve()))
