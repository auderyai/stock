from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QTextEdit, QVBoxLayout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from krx_research.collectors.xing_schema import REQUIRED_TRS, TrSchemaService


class Dialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LS xingAPI 통합 schema core")
        self.resize(900, 650)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "RES/JSON은 로더만 다르고, 이후에는 모두 동일한 TrSchema → PacketCodec 경로를 사용합니다."
        ))

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)

        button = QPushButton("6개 TR 공통 schema 로드 검사")
        button.clicked.connect(self.refresh)
        layout.addWidget(button)

        self.refresh()

    def refresh(self):
        service = TrSchemaService(ROOT)
        lines = []
        ready = 0

        for tr in REQUIRED_TRS:
            try:
                source = service.source(tr)
                schema = service.load(tr)
                ready += 1
                lines.append(f"{tr}: READY")
                lines.append(f"  source kind: {source.kind}")
                lines.append(f"  source: {source.path}")
                for block in schema.blocks:
                    lines.append(
                        f"  {block.name}: {block.direction}, "
                        f"size={block.size}, occurs={block.occurs}, fields={len(block.fields)}"
                    )
            except Exception as exc:
                lines.append(f"{tr}: ERROR -> {type(exc).__name__}: {exc}")
            lines.append("")

        lines.append(f"공통 TrSchema readiness: {ready}/{len(REQUIRED_TRS)}")
        lines.append(
            "실행 경로: Loader(RES/JSON) -> TrSchema -> PacketCodec -> XingRequestPlan"
        )
        self.text.setPlainText("\n".join(lines))


def main():
    app = QApplication(sys.argv)
    d = Dialog()
    d.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
