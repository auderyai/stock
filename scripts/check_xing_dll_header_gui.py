from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QTextEdit, QVBoxLayout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xingdll import XingInstallLayout


class Dialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LS xingAPI 32bit DLL / Header / RES 진단")
        self.resize(940, 720)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "중요: XingAPI.dll export 검사는 64bit 메인 Python이 아니라 "
            "32bit .venv_xing32 helper에서 수행합니다."
        ))
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        button = QPushButton("다시 검사")
        button.clicked.connect(self.refresh)
        layout.addWidget(button)
        self.refresh()

    def refresh(self):
        x = XingInstallLayout.discover()
        probe = x.probe_exports_32bit()
        headers = x.header_files()
        res = x.res_files()
        required = x.required_res()

        lines = [
            f"자동 선택 설치 폴더: {x.root}",
            f"XingAPI.dll: {x.dll} -> {'FOUND' if x.dll.is_file() else 'NOT FOUND'}",
            f"32bit worker Python: {x.xing32_python()} -> {'FOUND' if x.xing32_python().is_file() else 'NOT FOUND'}",
            "",
            f"Header root: {x.header_root} -> {'FOUND' if x.header_root.is_dir() else 'NOT FOUND'}",
            f"Header .h 전체 수: {len(headers)}",
        ]
        for p in headers[:50]:
            lines.append(f"  H: {p.relative_to(x.header_root) if x.header_root in p.parents else p}")
        if len(headers) > 50:
            lines.append(f"  ... 외 {len(headers)-50}개")

        lines += [
            "",
            f"Res root: {x.res_root} -> {'FOUND' if x.res_root.is_dir() else 'NOT FOUND'}",
            f"RES 전체 수: {len(res)}",
            "필수 TR RES:",
        ]
        for tr, path in required.items():
            lines.append(f"  {tr}: {path if path else 'NOT FOUND'}")

        lines += ["", "32bit DLL probe:"]
        lines.append(f"  probe ok: {probe.get('ok')}")
        lines.append(f"  python bits: {probe.get('python_bits', '-')}")
        if probe.get("error"):
            lines.append(f"  error: {probe['error']}")
        for name, ok in (probe.get("exports") or {}).items():
            lines.append(f"  {name}: {'PASS' if ok else 'FAIL'}")

        self.text.setPlainText("\n".join(lines))


def main():
    app = QApplication(sys.argv)
    d = Dialog()
    d.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
