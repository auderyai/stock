from __future__ import annotations

from collections import deque
import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QProcess
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing.worker_runtime import Xing32Environment


class Python32Locator:
    """Find an installed 32-bit Python without depending on py.exe."""

    @staticmethod
    def find() -> Path:
        roots = {Path(sys.base_prefix).parent, Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"}
        candidates = [Path(sys.executable)]
        for root in roots:
            if root.is_dir(): candidates += sorted(root.glob("Python*-32/python.exe"), reverse=True)
        for candidate in candidates:
            if not candidate.is_file():
                continue
            check = subprocess.run(
                [str(candidate), "-c", "import struct;print(struct.calcsize('P')*8)"],
                capture_output=True, text=True, timeout=10,
            )
            if check.returncode == 0 and check.stdout.strip() == "32":
                return candidate.resolve()
        raise FileNotFoundError("설치된 32bit Python을 찾지 못했습니다.")


class InstallerController:
    def __init__(self, process: QProcess, output, finished) -> None:
        self.process, self.output, self.finished_callback = process, output, finished
        self.queue: deque[tuple[str, list[str]]] = deque(); self.step = 0
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._finished)

    def start(self) -> None:
        source = Python32Locator.find()
        target = ROOT / ".venv_xing32" / "Scripts" / "python.exe"
        dll = Xing32Environment.install_root() / "XingAPI.dll"
        self.queue = deque([
            (str(source), ["-c", "import struct;assert struct.calcsize('P')*8==32;print('Python 32bit: OK')"]),
            (str(source), ["-m", "venv", str(ROOT / ".venv_xing32")]),
            (str(target), [str(ROOT / "scripts" / "probe_xing_dll_exports_32.py"), str(dll)]),
        ])
        self.step = 0; self._next()

    def _next(self) -> None:
        if not self.queue:
            self.finished_callback(True, "32bit XingAPI.dll 실행환경이 준비되었습니다."); return
        program, args = self.queue.popleft(); self.step += 1
        self.output(f"\n[{self.step}/3] {program} {' '.join(args)}")
        self.process.setWorkingDirectory(str(ROOT)); self.process.start(program, args)

    def _read(self) -> None:
        self.output(bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace"))

    def _finished(self, code: int, _status) -> None:
        self._read()
        if code:
            self.finished_callback(False, "32bit Python 또는 XingAPI.dll 상태를 위 로그에서 확인하십시오.")
        else:
            self._next()


class Window(QMainWindow):
    def __init__(self) -> None:
        super().__init__(); self.resize(800, 560); self.setWindowTitle("LS xingAPI 32bit 전용환경 설치")
        host = QWidget(); self.setCentralWidget(host); layout = QVBoxLayout(host)
        layout.addWidget(QLabel("메인 PySide6 환경과 분리하여 XingAPI.dll 전용 32bit 환경을 만듭니다."))
        self.log = QTextEdit(); self.log.setReadOnly(True); layout.addWidget(self.log, 1)
        self.bar = QProgressBar(); self.bar.setRange(0, 3); layout.addWidget(self.bar)
        self.button = QPushButton("32bit xingAPI 환경 만들기"); layout.addWidget(self.button)
        self.controller = InstallerController(QProcess(self), self._write, self._done)
        self.button.clicked.connect(self.start)

    def start(self) -> None:
        self.button.setEnabled(False); self.log.clear(); self.bar.setValue(0)
        try: self.controller.start()
        except Exception as exc: self._done(False, f"{type(exc).__name__}: {exc}")

    def _write(self, text: str) -> None:
        self.log.moveCursor(QTextCursor.End); self.log.insertPlainText(text)
        self.bar.setValue(self.controller.step)

    def _done(self, ok: bool, message: str) -> None:
        self.button.setEnabled(True); self.bar.setValue(3 if ok else self.controller.step)
        (QMessageBox.information if ok else QMessageBox.critical)(self, "완료" if ok else "설치 실패", message)


def main() -> int:
    app = QApplication(sys.argv); window = Window(); window.show(); return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
