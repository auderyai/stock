from __future__ import annotations

import datetime as dt
import os
import subprocess
import threading
from pathlib import Path
from typing import TextIO

from krx_research.application.job_menu.models import JobKind, JobRequest, JobResult, LegacyJobSpec
from krx_research.application.job_menu.ports import Progress


class PythonJobExecutor:
    """Infrastructure adapter executing the already-qualified production entrypoints.

    No extra console is created. stdout/stderr are streamed to the Qt worker and
    simultaneously persisted under logs/ as UTF-8.
    """

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()
        self._python = self._root / ".venv_krx_menu" / "Scripts" / "python.exe"
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def execute(self, request: JobRequest, progress: Progress | None = None) -> JobResult:
        command = self._build_command(request)
        return self._run(command, request.kind, progress)

    def execute_legacy(self, spec: LegacyJobSpec, progress: Progress | None = None) -> JobResult:
        launcher_root = self._root / "KRX_Menu_Launcher"
        batch = launcher_root / spec.batch_name if spec.batch_name else Path()
        if not batch.is_file():
            return JobResult(JobKind.MENU_2, 2, "", f"기존 작업 파일을 찾을 수 없습니다: {batch}")
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        command = [comspec, "/d", "/c", str(batch), *spec.arguments]
        # Legacy items are outside menu 2/5/7; result kind is only a transport placeholder.
        return self._run(command, JobKind.MENU_2, progress, log_prefix="legacy")

    def cancel(self) -> None:
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            pass

    def _build_command(self, request: JobRequest) -> list[str]:
        if not self._python.is_file():
            raise FileNotFoundError(f"가상환경 Python을 찾을 수 없습니다: {self._python}")
        drive_script = self._root / "scripts" / "stock_drive_sync.py"
        if request.kind == JobKind.DRIVE_VERIFY:
            return [str(self._python), str(drive_script), "verify"]
        if request.kind == JobKind.DRIVE_UPDATE:
            return [str(self._python), str(drive_script), "update-local"]
        if request.kind == JobKind.DRIVE_CLEANUP:
            return [
                str(self._python), str(drive_script), "cleanup-synced",
                "--through", request.end.isoformat(),
                "--confirm", "DELETE_SYNCED_DRIVE_DELTAS",
            ]
        if request.kind == JobKind.MENU_2:
            script = self._root / "scripts" / "run_daily_pipeline.py"
            return [
                str(self._python), str(script), "--as-of", request.end.isoformat(),
                "--until-complete", "--no-investor", "--markets", "KOSPI", "KOSDAQ",
            ]
        if request.kind == JobKind.MENU_5:
            script = self._root / "scripts" / "update_ls_investor_date_range.py"
            command = [
                str(self._python), str(script),
                "--start", request.start.isoformat(), "--end", request.end.isoformat(),
                "--chunk-days", str(request.chunk_days),
            ]
            if request.ticker:
                command.extend(["--ticker", request.ticker])
            return command
        if request.kind == JobKind.MENU_7:
            script = self._root / "scripts" / "run_xing_db_menu.py"
            command = [
                str(self._python), str(script), "--menu", "7",
                "--start", request.start.isoformat(), "--end", request.end.isoformat(),
                "--venues", ",".join(request.venues),
            ]
            if request.ticker:
                command.extend(["--ticker", request.ticker])
            if not request.include_investor:
                command.append("--no-investor")
            return command
        raise ValueError(f"지원하지 않는 메뉴: {request.kind}")

    def _run(
        self,
        command: list[str],
        kind: JobKind,
        progress: Progress | None,
        *,
        log_prefix: str | None = None,
    ) -> JobResult:
        logs = self._root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = log_prefix or f"menu{int(kind)}"
        log_path = logs / f"gui_{prefix}_{stamp}.log"
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with log_path.open("w", encoding="utf-8", newline="\n") as log:
            self._write(log, progress, "[EXEC] " + " ".join(command))
            process = subprocess.Popen(
                command,
                cwd=str(self._root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            with self._lock:
                self._process = process
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    self._write(log, progress, line.rstrip("\r\n"))
                rc = process.wait()
            finally:
                with self._lock:
                    if self._process is process:
                        self._process = None
        summary = "정상 완료" if rc == 0 else f"오류 종료({rc})"
        return JobResult(kind, rc, str(log_path), summary)

    @staticmethod
    def _write(log: TextIO, progress: Progress | None, message: str) -> None:
        log.write(message + "\n")
        log.flush()
        if progress is not None:
            progress(message)
