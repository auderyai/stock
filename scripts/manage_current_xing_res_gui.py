from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QPushButton, QTextEdit, QVBoxLayout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing_schema import CurrentXingResManager, CURRENT_RES_TRS, BLOCKED_TRS


class Dialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LS 최신 xingAPI RES 관리")
        self.resize(900, 650)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "최신 공식 설치본에서 확인된 t8424/t8436/t8429/t8451 RES만 "
            "C:\\stock 관리 폴더로 복사합니다.\n"
            "설치 원본은 수정하지 않습니다. t1516/t1702는 최신 명세 확인 전까지 BLOCKED 상태로 유지합니다."
        ))

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)

        import_btn = QPushButton("현재 공식 RES 4종을 Stock으로 복사")
        import_btn.clicked.connect(self.import_res)
        layout.addWidget(import_btn)

        refresh_btn = QPushButton("다시 검사")
        refresh_btn.clicked.connect(self.refresh)
        layout.addWidget(refresh_btn)

        self.refresh()

    def refresh(self) -> None:
        m = CurrentXingResManager(ROOT)
        s = m.status()

        lines = [
            f"설치 폴더: {s['install_root']}",
            f"공식 Res: {s['source_res']}",
            f"C:\\stock 관리 Res: {s['managed_res']}",
            "",
            "현재 최신 설치본 RES:",
        ]

        discovered = s["discovered"]
        for tr in CURRENT_RES_TRS:
            files = discovered[tr]
            if files:
                lines.append(f"  {tr}:")
                for p in files:
                    lines.append(f"    FOUND -> {p}")
            else:
                lines.append(f"  {tr}: NOT FOUND")

        lines += ["", "최신 명세 확인 전 차단:"]
        for tr in BLOCKED_TRS:
            lines.append(f"  {tr}: BLOCKED")

        lines += [
            "",
            f"manifest: {s['manifest'] or '아직 생성되지 않음'}",
        ]
        self.text.setPlainText("\n".join(lines))

    def import_res(self) -> None:
        try:
            records = CurrentXingResManager(ROOT).import_current()
        except Exception as exc:
            QMessageBox.critical(self, "복사 실패", f"{type(exc).__name__}: {exc}")
            return

        QMessageBox.information(
            self,
            "복사 완료",
            f"{len(records)}개 RES 파일을 C:\\stock 관리 폴더에 복사했습니다.\n"
            "t1516/t1702는 계속 BLOCKED입니다.",
        )
        self.refresh()


def main() -> int:
    app = QApplication(sys.argv)
    d = Dialog()
    d.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
