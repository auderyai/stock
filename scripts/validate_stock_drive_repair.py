from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_FILES = {
    "requirements-cloud-worker.txt",
    "scripts/stock_drive_sync.py",
    "scripts/run_cloud_xing_stage.py",
    "tests/application/test_xing_db_menu5_retry.py",
    "tests/application/test_xing_db_menu7_retry.py",
}
ALLOWED_PREFIXES = (
    "src/krx_research/application/xing_db/",
    "src/krx_research/cloud_sync/",
    "src/krx_research/infrastructure/xing_db/",
    "tests/cloud_sync/",
)
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=True,
    )


def _changed_files() -> list[str]:
    lines = _run("git", "status", "--porcelain").stdout.splitlines()
    return sorted({line[3:].replace("\\", "/") for line in lines if len(line) > 3})


def _allowed(path: str) -> bool:
    return path in ALLOWED_FILES or path.startswith(ALLOWED_PREFIXES)


def validate_scope(paths: list[str]) -> None:
    if not paths:
        raise RuntimeError("Codex가 수정한 파일이 없습니다.")
    if len(paths) > 16:
        raise RuntimeError(f"자동 수정 파일이 너무 많습니다: {len(paths)}")
    forbidden = [path for path in paths if not _allowed(path)]
    if forbidden:
        raise RuntimeError("허용되지 않은 자동 수정: " + ", ".join(forbidden))
    symlinks = [path for path in paths if (ROOT / path).is_symlink()]
    if symlinks:
        raise RuntimeError("심볼릭 링크 자동 수정은 허용되지 않습니다: " + ", ".join(symlinks))
    invalid_types = [
        path for path in paths
        if (ROOT / path).is_file() and (ROOT / path).suffix not in {".py", ".txt"}
    ]
    if invalid_types:
        raise RuntimeError("허용되지 않은 파일 형식: " + ", ".join(invalid_types))
    total_bytes = sum((ROOT / path).stat().st_size for path in paths if (ROOT / path).is_file())
    if total_bytes > 512_000:
        raise RuntimeError("자동 수정 파일 크기가 512KB를 초과했습니다.")
    tracked = set(_run("git", "ls-files").stdout.splitlines())
    tracked_lines = sum(
        int(added) + int(deleted)
        for added, deleted, *_ in (
            line.split("\t") for line in _run("git", "diff", "HEAD", "--numstat").stdout.splitlines()
        )
        if added.isdigit() and deleted.isdigit()
    )
    untracked_lines = sum(
        len((ROOT / path).read_text(encoding="utf-8", errors="replace").splitlines())
        for path in paths
        if (ROOT / path).is_file() and path not in tracked
    )
    if tracked_lines + untracked_lines > 800:
        raise RuntimeError("자동 수정 범위가 800줄을 초과했습니다.")
    content = "\n".join(
        (ROOT / path).read_text(encoding="utf-8", errors="replace")
        for path in paths if (ROOT / path).is_file()
    )
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        raise RuntimeError("자동 수정에서 비밀값 형식이 감지되었습니다.")


def verify() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    commands = (
        (sys.executable, "-m", "unittest", "discover", "-s", "tests/cloud_sync", "-p", "test_*.py"),
        (sys.executable, "-m", "unittest", "tests.application.test_xing_db_menu5_retry", "tests.application.test_xing_db_menu7_retry"),
        (sys.executable, "-m", "compileall", "-q", "scripts/stock_drive_sync.py", "scripts/run_cloud_xing_stage.py", "src/krx_research/cloud_sync", "src/krx_research/infrastructure/xing_db"),
    )
    for command in commands:
        subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> int:
    paths = _changed_files()
    validate_scope(paths)
    verify()
    print(f"[PASS] 제한된 Stock Drive 자동 수정 검증: {len(paths)}개 파일")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
