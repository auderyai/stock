from __future__ import annotations

import datetime as dt
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

LAUNCHER_ROOT = Path(__file__).resolve().parent.parent


class ProjectLocator:
    def __init__(self, launcher_root: Path = LAUNCHER_ROOT) -> None:
        self._launcher_root = launcher_root

    def locate(self) -> Path:
        root = self._launcher_root.parent.resolve()
        if (root / "scripts" / "run_workstation_gui.py").is_file():
            return root
        raise RuntimeError(r"C:\stock 프로젝트를 찾지 못했습니다.")


@dataclass(frozen=True)
class ProgressJob:
    key: str
    title: str
    description: str
    command: tuple[str, ...]


class ProgressJobCatalog:
    JOBS = {
        "daily": ProgressJob(
            "daily",
            "2. 빠른 일봉 갱신 (수급 제외)",
            "PostgreSQL 일봉 + 32bit xingAPI Worker 지수 구성/업종지수 갱신",
            ("run_fast_daily_update.py",),
        ),
        "supplement": ProgressJob(
            "supplement",
            "7. LS 종목별 일봉·수급 원본 보완",
            "LS 종목별 일봉·수급 원본 보완",
            ("run_daily_integrated.py", "--ls-supplement"),
        ),
    }

    @classmethod
    def get(cls, key: str) -> ProgressJob:
        try:
            return cls.JOBS[key]
        except KeyError as exc:
            raise ValueError(f"알 수 없는 작업: {key}") from exc


class JobLogService:
    """Keep exactly one latest log per managed job."""

    def __init__(self, project_root: Path, job_key: str) -> None:
        self.directory = project_root / "logs"
        self.path = self.directory / f"{job_key}.log"

    def start(self, title: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.path.unlink()
        self._write(f"[START] {dt.datetime.now():%Y-%m-%d %H:%M:%S} | {title}")

    def append(self, line: str) -> None:
        self._write(line)

    def finish(self, result: str, code: int, elapsed: float) -> None:
        self._write(
            f"[END] {dt.datetime.now():%Y-%m-%d %H:%M:%S} | "
            f"{result} | exit={code} | elapsed={elapsed:.0f}s"
        )

    def _write(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip("\n") + "\n")


def extract_progress(line: str) -> tuple[int, int] | None:
    patterns = (
        r"\[(\d+)\s*/\s*(\d+)\]",
        r"(?:진행\s*[:：]?\s*)?(\d+)\s*/\s*(\d+)\s*(?:종목|건|개|행)?",
    )
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            current, total = map(int, match.groups())
            if total > 0 and 0 <= current <= total:
                return current, total
    return None


class ProgressWindow(QMainWindow):
    """Own one QProcess and expose all failures instead of hiding pythonw errors."""

    def __init__(self, job: ProgressJob, extra_args: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.job = job
        self.extra_args = extra_args
        self.root_path = ProjectLocator().locate()
        self.started_at = time.monotonic()
        self.job_log = JobLogService(self.root_path, job.key)
        self.job_log.start(job.title)
        self._build_ui()
        self._configure_process()
        self.start_job()

    def _build_ui(self) -> None:
        self.resize(980, 700)
        self.setWindowTitle(f"{self.job.title} - 진행현황")
        host = QWidget()
        self.setCentralWidget(host)
        layout = QVBoxLayout(host)
        layout.addWidget(QLabel(self.job.description))
        self.status = QLabel("작업 시작 준비 중...")
        layout.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        layout.addWidget(self.bar)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)
        self.log_path = QLabel(f"로그: {self.job_log.path}")
        layout.addWidget(self.log_path)
        self.open_log = QPushButton("로그 열기")
        self.open_log.clicked.connect(self.open_log_file)
        layout.addWidget(self.open_log)
        self.stop = QPushButton("중지")
        self.stop.clicked.connect(self.stop_job)
        layout.addWidget(self.stop)

    def _configure_process(self) -> None:
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.started.connect(lambda: self.status.setText("실행 중..."))
        self.process.errorOccurred.connect(self.process_error)
        self.process.finished.connect(self.finished)

    def python_exe(self) -> Path:
        executable = self.root_path / ".venv" / "Scripts" / "python.exe"
        if not executable.is_file():
            raise FileNotFoundError(f"가상환경 Python이 없습니다: {executable}")
        return executable

    def start_job(self) -> None:
        try:
            script = self.root_path / "scripts" / self.job.command[0]
            if not script.is_file():
                raise FileNotFoundError(f"작업 스크립트가 없습니다: {script}")
            args = [str(script), *self.job.command[1:], *self.extra_args]
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert("PYTHONPATH", str(self.root_path / "src"))
            environment.insert("PYTHONUTF8", "1")
            environment.insert("PYTHONIOENCODING", "utf-8")
            self.process.setWorkingDirectory(str(self.root_path))
            self.process.setProcessEnvironment(environment)
            self.status.setText("프로세스 시작 중...")
            self.process.start(str(self.python_exe()), args)
        except Exception as exc:
            self.status.setText("실행 준비 실패")
            message = str(exc)
            self.log.append(message)
            self.job_log.append(f"[PREPARE ERROR] {message}")
            self.job_log.finish("실행 준비 실패", -1, time.monotonic() - self.started_at)
            QMessageBox.critical(self, "작업 실행 오류", message)
            self._finish_button()

    def read_output(self) -> None:
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            self.log.append(line)
            self.job_log.append(line)
            progress = extract_progress(line)
            if progress:
                current, total = progress
                self.bar.setValue(int(current / total * 100))
                self.status.setText(f"{current:,}/{total:,}")

    def process_error(self, _error: QProcess.ProcessError) -> None:
        message = self.process.errorString() or "프로세스 실행 오류"
        self.status.setText(f"실행 오류: {message}")
        line = f"[실행 오류] {message}"
        self.log.append(line)
        self.job_log.append(line)

    def finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        self.read_output()
        elapsed = time.monotonic() - self.started_at
        result = "정상 완료" if code == 0 else "미완료/오류"
        summary = f"{result} · 종료코드 {code} · {elapsed:,.0f}초"
        self.status.setText(summary)
        self.job_log.finish(result, code, elapsed)
        if code == 0:
            self.bar.setValue(100)
        self._finish_button()
        QMessageBox.information(
            self,
            "작업 완료" if code == 0 else "작업 미완료/오류",
            f"{self.job.title}\n{summary}\n\n로그: {self.job_log.path}",
        )

    def _finish_button(self) -> None:
        try:
            self.stop.clicked.disconnect()
        except RuntimeError:
            pass
        self.stop.setText("닫기")
        self.stop.clicked.connect(self.close)

    def open_log_file(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.job_log.path)))

    def stop_job(self) -> None:
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.status.setText("중지 요청됨")


def launch(job_key: str, extra_args: tuple[str, ...] = ()) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = ProgressWindow(ProgressJobCatalog.get(job_key), extra_args)
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("사용법: run_job_progress_gui.py <daily|supplement> [추가 인수]")
    return launch(args[0], tuple(args[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
