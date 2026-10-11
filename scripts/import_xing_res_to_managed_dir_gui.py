from __future__ import annotations

import os
import shutil
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
MANAGED = ROOT / "resources" / "xing" / "res"
REQUIRED = ("t8424", "t8436", "t1516", "t8429", "t8451", "t1702")


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


class ResImporter:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.root = source.parent if source.is_file() else source
        self.managed = MANAGED
        self.managed.mkdir(parents=True, exist_ok=True)

    def find(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        if not self.root.exists():
            return found

        # Search only the user-selected package/install tree.
        try:
            for current, dirs, files in os.walk(self.root):
                current_path = Path(current)
                # Avoid walking huge unrelated trees if a broad folder is selected.
                try:
                    depth = len(current_path.relative_to(self.root).parts)
                except ValueError:
                    depth = 0
                if depth >= 6:
                    dirs[:] = []
                lowered = {name.lower(): name for name in files}
                for tr in REQUIRED:
                    filename = f"{tr}.res"
                    real = lowered.get(filename.lower())
                    if real and tr not in found:
                        found[tr] = current_path / real
                if len(found) == len(REQUIRED):
                    break
        except OSError:
            pass
        return found

    def copy(self, found: dict[str, Path]) -> tuple[int, tuple[str, ...]]:
        copied = 0
        for tr, source in found.items():
            target = self.managed / f"{tr}.res"
            shutil.copy2(source, target)
            copied += 1
        missing = tuple(tr for tr in REQUIRED if not (self.managed / f"{tr}.res").is_file())
        return copied, missing


class Dialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LS xingAPI RES 가져오기")
        self.resize(820, 600)
        MANAGED.mkdir(parents=True, exist_ok=True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "LS/DevCenter의 공식 RES 파일을 C:\\stock 관리 폴더로 1회 복사합니다.\n"
            f"대상 폴더: {MANAGED}\n\n"
            "DevCenter.exe 또는 DevCenter/LS xingAPI 설치 폴더를 선택하십시오. "
            "프로그램은 선택한 위치 내부만 검색합니다."
        ))

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)

        choose_exe = QPushButton("DevCenter.exe 선택 후 가져오기")
        choose_exe.clicked.connect(self.choose_exe)
        layout.addWidget(choose_exe)

        choose_folder = QPushButton("LS/DevCenter 폴더 선택 후 가져오기")
        choose_folder.clicked.connect(self.choose_folder)
        layout.addWidget(choose_folder)

        self.refresh()

    def current_status(self) -> list[str]:
        lines = ["현재 C:\\stock 관리 폴더 상태:"]
        for tr in REQUIRED:
            path = MANAGED / f"{tr}.res"
            lines.append(f"  {tr}.res : {'FOUND' if path.is_file() else 'NOT FOUND'}")
        count = sum((MANAGED / f"{tr}.res").is_file() for tr in REQUIRED)
        lines.extend(("", f"확인 결과: {count}/{len(REQUIRED)}"))
        return lines

    def refresh(self, prefix: list[str] | None = None) -> None:
        lines = list(prefix or [])
        if lines:
            lines.append("")
        lines.extend(self.current_status())
        self.text.setPlainText("\n".join(lines))

    def choose_exe(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "DevCenter.exe를 선택하십시오",
            str(Path.home()),
            "Executable (*.exe);;All files (*)",
        )
        if selected:
            self.import_from(Path(selected))

    def choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "LS xingAPI 또는 DevCenter 설치 폴더를 선택하십시오",
            str(Path(r"C:\LS_SEC")) if Path(r"C:\LS_SEC").exists() else str(Path.home()),
        )
        if selected:
            self.import_from(Path(selected))

    def import_from(self, source: Path) -> None:
        importer = ResImporter(source)
        found = importer.find()

        lines = [f"선택 위치: {source}", "", "검색 결과:"]
        for tr in REQUIRED:
            path = found.get(tr)
            lines.append(f"  {tr}.res : {path if path else 'NOT FOUND'}")

        if not found:
            self.refresh(lines)
            QMessageBox.critical(
                self,
                "RES 파일 없음",
                "선택한 위치에서 필요한 xingAPI RES 파일을 찾지 못했습니다.\n"
                "정상 실행되는 DevCenter.exe가 있는 설치 폴더를 선택하십시오.",
            )
            return

        copied, missing = importer.copy(found)
        lines.extend(("", f"복사: {copied}개", f"남은 누락: {len(missing)}개"))
        self.refresh(lines)

        if missing:
            QMessageBox.warning(
                self,
                "일부 파일만 가져옴",
                "찾은 RES 파일은 C:\\stock 관리 폴더로 복사했습니다.\n\n"
                "아직 누락:\n" + "\n".join(f"- {tr}.res" for tr in missing)
                + "\n\n다른 DevCenter/LS 설치 위치를 추가로 선택해도 됩니다.",
            )
            return

        EnvRepository(ROOT / ".env").save("LS_XING_RES_DIR", str(MANAGED.resolve()))
        os.environ["LS_XING_RES_DIR"] = str(MANAGED.resolve())
        QMessageBox.information(
            self,
            "완료",
            "필수 RES 6개를 모두 C:\\stock 관리 폴더에 준비했습니다.\n"
            "LS_XING_RES_DIR도 해당 폴더로 저장했습니다.",
        )


def main() -> int:
    app = QApplication(sys.argv)
    dialog = Dialog()
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
