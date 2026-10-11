from __future__ import annotations

import os
from pathlib import Path
import sys

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

from krx_research.collectors.xing.query import XingResLocator


class EnvRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, key: str, value: str) -> None:
        lines = self.path.read_text(encoding="utf-8-sig").splitlines() if self.path.is_file() else []
        output: list[str] = []
        replaced = False

        for line in lines:
            stripped = line.strip()
            if "=" in stripped and stripped.split("=", 1)[0].strip() == key:
                output.append(f"{key}={value}")
                replaced = True
            else:
                output.append(line)

        if not replaced:
            if output and output[-1] != "":
                output.append("")
            output.append(f"{key}={value}")

        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


class ManagedResSetupDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Stock xingAPI RES 폴더 등록")
        self.resize(780, 540)

        self.managed = XingResLocator.managed_root().resolve()
        self.managed.mkdir(parents=True, exist_ok=True)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "C:\\stock이 관리하는 단일 RES 폴더를 사용합니다.\n\n"
                f"관리 폴더:\n{self.managed}\n\n"
                "이 폴더를 선택하여 .env에 저장합니다. "
                "필수 RES 6개가 모두 없으면 저장을 허용하지 않습니다."
            )
        )

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)

        choose = QPushButton("Stock RES 폴더 선택 및 저장")
        choose.clicked.connect(self.choose)
        layout.addWidget(choose)

        self.refresh()

    def refresh(self) -> None:
        configured = XingResLocator._env_value("LS_XING_RES_DIR")
        lines = [
            f"관리 폴더: {self.managed}",
            f"현재 LS_XING_RES_DIR: {configured or '(미지정)'}",
            "",
            "필수 RES 상태:",
        ]
        for tr in XingResLocator.REQUIRED_TRS:
            path = self.managed / f"{tr}.res"
            lines.append(f"  {tr}.res : {'FOUND' if path.is_file() else 'NOT FOUND'}")

        lines.extend(
            (
                "",
                f"확인 결과: {XingResLocator.score(self.managed)}/{len(XingResLocator.REQUIRED_TRS)}",
            )
        )
        self.text.setPlainText("\n".join(lines))

    def choose(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "C:\\stock의 xingAPI RES 관리 폴더를 선택하십시오",
            str(self.managed),
        )
        if not selected:
            return

        selected_path = Path(selected).resolve()
        if selected_path != self.managed:
            QMessageBox.critical(
                self,
                "다른 폴더 선택",
                "외부 Downloads/DevCenter 폴더는 더 이상 사용하지 않습니다.\n"
                f"다음 폴더를 선택하십시오:\n{self.managed}",
            )
            return

        missing = XingResLocator.missing(selected_path)
        if missing:
            QMessageBox.critical(
                self,
                "필수 RES 파일 누락",
                "아직 저장할 수 없습니다.\n\n"
                "다음 파일이 C:\\stock 관리 폴더에 없습니다:\n"
                + "\n".join(f"- {tr}.res" for tr in missing),
            )
            self.refresh()
            return

        EnvRepository(ROOT / ".env").save("LS_XING_RES_DIR", str(selected_path))
        os.environ["LS_XING_RES_DIR"] = str(selected_path)
        QMessageBox.information(
            self,
            "저장 완료",
            "C:\\stock 관리 RES 폴더를 공통 xingAPI RES 경로로 저장했습니다.",
        )
        self.refresh()


def main() -> int:
    app = QApplication(sys.argv)
    dialog = ManagedResSetupDialog()
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
