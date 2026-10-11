from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitCommandResult:
    stdout: str
    returncode: int = 0


class GitService:
    """Small Git service for the C:\\stock working tree."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _run(self, args: Sequence[str], *, check: bool = True) -> GitCommandResult:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if check and proc.returncode:
            message = (proc.stderr or proc.stdout).strip()
            raise GitError(message or f"git {' '.join(args)} failed")
        return GitCommandResult(proc.stdout.strip(), proc.returncode)

    def ensure_git_available(self) -> None:
        try:
            subprocess.run(["git", "--version"], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise GitError("Git for Windows가 설치되어 있지 않거나 PATH에서 찾을 수 없습니다.") from exc

    def is_repository(self) -> bool:
        return self._run(["rev-parse", "--is-inside-work-tree"], check=False).returncode == 0

    def init_repository(self) -> None:
        self.ensure_git_available()
        if not self.is_repository():
            result = self._run(["init", "-b", "main"], check=False)
            if result.returncode:
                self._run(["init"])
                self._run(["branch", "-M", "main"], check=False)

    def identity(self) -> tuple[str, str]:
        name = self._run(["config", "user.name"], check=False).stdout
        email = self._run(["config", "user.email"], check=False).stdout
        return name, email

    def configure_identity(self, name: str, email: str) -> None:
        if name:
            self._run(["config", "user.name", name])
        if email:
            self._run(["config", "user.email", email])

    def require_identity(self) -> None:
        name, email = self.identity()
        if not name or not email:
            raise GitError(
                "Git 사용자 정보가 없습니다. GIT_SETUP_NEW_STOCK.cmd를 실행해 user.name/user.email을 설정하십시오."
            )

    def has_head(self) -> bool:
        return self._run(["rev-parse", "--verify", "HEAD"], check=False).returncode == 0

    def is_dirty(self) -> bool:
        return bool(self._run(["status", "--porcelain"]).stdout)

    def commit_all(self, message: str, *, allow_empty: bool = False) -> bool:
        self.require_identity()
        self._run(["add", "-A"])
        if not allow_empty and not self.is_dirty():
            return False
        args = ["commit", "-m", message]
        if allow_empty:
            args.insert(1, "--allow-empty")
        self._run(args)
        return True

    def initialize_baseline(self) -> bool:
        self.init_repository()
        if self.has_head():
            return False
        return self.commit_all("baseline: Stock before managed patch workflow", allow_empty=True)

    def checkpoint(self, message: str | None = None) -> bool:
        self.init_repository()
        if not self.has_head():
            return self.initialize_baseline()
        if not self.is_dirty():
            return False
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self.commit_all(message or f"checkpoint: before patch {stamp}")

    def status(self) -> str:
        self.init_repository()
        branch = self._run(["branch", "--show-current"]).stdout or "(detached)"
        status = self._run(["status", "--short"]).stdout or "clean"
        return f"branch: {branch}\n{status}"

    def log(self, count: int = 12) -> str:
        self.init_repository()
        if not self.has_head():
            return "No commits yet."
        return self._run(["log", f"-{count}", "--oneline", "--decorate"]).stdout


class GitApplication:
    def __init__(self, service: GitService) -> None:
        self.service = service

    def run(self, command: str, args: argparse.Namespace) -> int:
        try:
            if command == "init":
                self.service.init_repository()
                if args.name or args.email:
                    self.service.configure_identity(args.name or "", args.email or "")
                self.service.require_identity()
                created = self.service.initialize_baseline()
                print("[OK] Git repository ready." + (" Baseline commit created." if created else ""))
            elif command == "checkpoint":
                created = self.service.checkpoint(args.message)
                print("[OK] checkpoint created." if created else "[OK] working tree already clean.")
            elif command == "commit":
                self.service.init_repository()
                created = self.service.commit_all(args.message)
                print("[OK] commit created." if created else "[OK] no changes to commit.")
            elif command == "status":
                print(self.service.status())
            elif command == "log":
                print(self.service.log(args.count))
            else:
                raise GitError(f"Unsupported command: {command}")
            return 0
        except GitError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stock Git workflow")
    parser.add_argument("--root", default=os.environ.get("STOCK_ROOT", r"C:\stock"))
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--name")
    init.add_argument("--email")

    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("--message")

    commit = sub.add_parser("commit")
    commit.add_argument("--message", required=True)

    sub.add_parser("status")
    log = sub.add_parser("log")
    log.add_argument("--count", type=int, default=12)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    return GitApplication(GitService(root)).run(args.command, args)


if __name__ == "__main__":
    raise SystemExit(main())
