from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path


def _console_write(text: str) -> None:
    stream = sys.stdout
    encoding = stream.encoding or "utf-8"
    safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    stream.write(safe)
    stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="V41.10 E2E runner with UTF-8 logging")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    python = root / ".venv" / "Scripts" / "python.exe"
    verifier = root / "scripts" / "verify_v41_db_menu_e2e.py"
    log = args.log
    if log is None:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        log = root / "logs" / f"v41_10_db_menu_e2e_{stamp}.log"
    else:
        log = log.expanduser().resolve()

    if not python.is_file():
        _console_write(f"[ERROR] Python executable not found: {python}\n")
        return 2
    if not verifier.is_file():
        _console_write(f"[ERROR] Verifier not found: {verifier}\n")
        return 3

    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    _console_write(f"[LOG] {log}\n")
    with log.open("w", encoding="utf-8", newline="") as fp:
        process = subprocess.Popen(
            [str(python), str(verifier)],
            cwd=str(root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        assert process.stdout is not None
        while True:
            raw = process.stdout.readline()
            if not raw:
                if process.poll() is not None:
                    break
                continue
            text = raw.decode("utf-8", errors="replace")
            fp.write(text)
            fp.flush()
            _console_write(text)
        rc = process.wait()

    _console_write(f"[LOG] {log}\n")
    return int(rc)


if __name__ == "__main__":
    raise SystemExit(main())
