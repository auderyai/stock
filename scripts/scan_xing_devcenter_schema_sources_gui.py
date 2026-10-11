from __future__ import annotations

import os
from pathlib import Path
import re
import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QLabel, QPushButton, QTextEdit, QVBoxLayout
)

ROOT = Path(__file__).resolve().parents[1]
INSTALL = Path(r"C:\LS_SEC\xingAPI_Program(2025.06.07)")
TRS = ("t8424", "t8436", "t1516", "t8429", "t8451", "t1702")

TEXT_EXTS = {
    ".txt", ".ini", ".cfg", ".conf", ".xml", ".json", ".csv",
    ".h", ".hpp", ".c", ".cpp", ".py", ".res", ".dat", ".def",
}
MAX_FILE_SIZE = 32 * 1024 * 1024


def byte_patterns(tr: str) -> tuple[bytes, ...]:
    raw = tr.encode("ascii")
    utf16le = tr.encode("utf-16le")
    utf16be = tr.encode("utf-16be")
    return raw, utf16le, utf16be


class ScanWorker(QThread):
    completed = Signal(str)

    def run(self) -> None:
        lines: list[str] = []
        lines.append(f"설치 폴더: {INSTALL}")
        lines.append(f"존재: {INSTALL.is_dir()}")
        lines.append("")

        if not INSTALL.is_dir():
            self.completed.emit("\n".join(lines))
            return

        filename_hits: dict[str, list[Path]] = {tr: [] for tr in TRS}
        content_hits: dict[str, list[tuple[Path, str]]] = {tr: [] for tr in TRS}
        scanned = 0
        skipped = 0

        for current, dirs, files in os.walk(INSTALL):
            current_path = Path(current)
            # Avoid temp/cache-like areas if any appear.
            dirs[:] = [d for d in dirs if d.lower() not in {"temp", "tmp", "cache", "__pycache__"}]

            for name in files:
                p = current_path / name
                scanned += 1

                lower_name = name.lower()
                for tr in TRS:
                    if tr in lower_name:
                        filename_hits[tr].append(p)

                try:
                    size = p.stat().st_size
                except OSError:
                    skipped += 1
                    continue

                if size <= 0 or size > MAX_FILE_SIZE:
                    skipped += 1
                    continue

                try:
                    data = p.read_bytes()
                except OSError:
                    skipped += 1
                    continue

                for tr in TRS:
                    pats = byte_patterns(tr)
                    matched = None
                    if pats[0] in data:
                        matched = "ASCII/UTF-8"
                    elif pats[1] in data:
                        matched = "UTF-16LE"
                    elif pats[2] in data:
                        matched = "UTF-16BE"
                    if matched:
                        content_hits[tr].append((p, matched))

        lines.append(f"검색 파일 수: {scanned}")
        lines.append(f"건너뜀: {skipped}")
        lines.append("")

        for tr in TRS:
            lines.append("=" * 72)
            lines.append(f"[{tr}]")
            lines.append("")
            lines.append("파일명 일치:")
            if filename_hits[tr]:
                for p in filename_hits[tr][:50]:
                    lines.append(f"  {p}")
            else:
                lines.append("  없음")

            lines.append("")
            lines.append("파일 내용 일치:")
            if content_hits[tr]:
                for p, enc in content_hits[tr][:100]:
                    lines.append(f"  {p} [{enc}]")
            else:
                lines.append("  없음")
            lines.append("")

        # Highlight directories that contain hits for several required TRs.
        dir_scores: dict[Path, set[str]] = {}
        for tr, hits in content_hits.items():
            for p, _ in hits:
                dir_scores.setdefault(p.parent, set()).add(tr)

        lines.append("=" * 72)
        lines.append("여러 필수 TR가 함께 발견된 폴더:")
        ranked = sorted(dir_scores.items(), key=lambda item: (-len(item[1]), str(item[0]).lower()))
        if ranked:
            for directory, trs in ranked[:50]:
                lines.append(f"  {len(trs)}/6 {directory} -> {', '.join(sorted(trs))}")
        else:
            lines.append("  없음")

        self.completed.emit("\n".join(lines))


class Dialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LS DevCenter 최신 TR 명세 저장위치 진단")
        self.resize(980, 760)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "읽기 전용 진단입니다. 최신 xingAPI 설치 폴더 내부에서 "
            "t8424/t8436/t1516/t8429/t8451/t1702 문자열이 저장된 파일을 찾습니다.\n"
            "파일을 수정하거나 삭제하지 않습니다."
        ))

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)

        self.button = QPushButton("최신 DevCenter TR 저장위치 검사")
        self.button.clicked.connect(self.start_scan)
        layout.addWidget(self.button)

        self.worker: ScanWorker | None = None

    def start_scan(self) -> None:
        self.button.setEnabled(False)
        self.text.setPlainText("검사 중...\n파일 수에 따라 잠시 걸릴 수 있습니다.")
        self.worker = ScanWorker()
        self.worker.completed.connect(self.done)
        self.worker.start()

    def done(self, text: str) -> None:
        self.text.setPlainText(text)
        self.button.setEnabled(True)


def main() -> int:
    app = QApplication(sys.argv)
    dialog = Dialog()
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
