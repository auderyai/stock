from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xingdll import REQUIRED_TRS, XingDllReadiness


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class PacketZipAudit:
    def __init__(self, zip_path: Path) -> None:
        self.zip_path = zip_path

    def inspect(self) -> dict[str, object]:
        result: dict[str, object] = {
            "zip": str(self.zip_path),
            "sha256": sha256(self.zip_path),
            "targets": {},
            "all_packet_headers": 0,
        }
        with zipfile.ZipFile(self.zip_path) as z:
            names = z.namelist()
            packet_headers = [
                n for n in names
                if "/packet/" in n.lower() and n.lower().endswith(".h")
            ]
            result["all_packet_headers"] = len(packet_headers)

            for tr in REQUIRED_TRS:
                filename = f"{tr}.h"
                hits = [
                    n for n in packet_headers
                    if Path(n).name.lower() == filename.lower()
                ]
                result["targets"][tr] = hits

        return result


class Dialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LS xingAPI DLL packet schema 감사")
        self.resize(900, 680)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "DLL transport와 packet schema를 분리해서 검사합니다.\n"
            "transport가 PASS여도 필수 TR schema가 없으면 실제 메뉴 런타임은 전환하지 않습니다."
        ))

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)

        choose = QPushButton("DLL.zip 샘플 선택 후 packet header 감사")
        choose.clicked.connect(self.choose_zip)
        layout.addWidget(choose)

        refresh = QPushButton("현재 readiness 다시 검사")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)

        self.refresh()

    def refresh(self, extra: list[str] | None = None) -> None:
        r = XingDllReadiness.discover()
        lines = [
            f"설치 폴더: {r.install_root}",
            f"XingAPI.dll: {r.dll_path} -> {'FOUND' if r.dll_path.is_file() else 'NOT FOUND'}",
            f"DLL transport: {'READY' if r.transport_ready else 'NOT READY'}",
            "",
            "프로젝트 packet schema:",
        ]
        for tr in REQUIRED_TRS:
            path = r.schemas[tr]
            lines.append(f"  {tr}: {path if path else 'NOT READY'}")

        lines += [
            "",
            f"schema 누락: {', '.join(r.missing_schemas) if r.missing_schemas else '없음'}",
            f"최종 DLL runtime: {'READY' if r.runtime_ready else 'BLOCKED'}",
        ]

        if extra:
            lines += ["", *extra]

        self.text.setPlainText("\n".join(lines))

    def choose_zip(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "LS xingAPI DLL 샘플 ZIP을 선택하십시오",
            str(Path.home()),
            "ZIP files (*.zip);;All files (*)",
        )
        if not selected:
            return

        try:
            report = PacketZipAudit(Path(selected)).inspect()
        except Exception as exc:
            QMessageBox.critical(self, "감사 실패", f"{type(exc).__name__}: {exc}")
            return

        target_map = report["targets"]
        lines = [
            "선택 ZIP 감사 결과:",
            f"  파일: {report['zip']}",
            f"  SHA256: {report['sha256']}",
            f"  packet/*.h 전체 수: {report['all_packet_headers']}",
            "",
            "필수 TR header:",
        ]
        found = 0
        for tr in REQUIRED_TRS:
            hits = target_map.get(tr) or []
            if hits:
                found += 1
                lines.append(f"  {tr}: FOUND -> {hits[0]}")
            else:
                lines.append(f"  {tr}: NOT FOUND")

        lines += [
            "",
            f"샘플 ZIP 필수 header: {found}/{len(REQUIRED_TRS)}",
            "",
            "주의: 샘플 ZIP의 header는 참고용입니다.",
            "최신 LS 배포판/DevCenter 명세와 일치가 확인되기 전에는 runtime schema로 승격하지 않습니다.",
        ]
        self.refresh(lines)


def main() -> int:
    app = QApplication(sys.argv)
    d = Dialog()
    d.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
