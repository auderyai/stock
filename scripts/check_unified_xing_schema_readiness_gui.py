from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication,QDialog,QLabel,QPushButton,QTextEdit,QVBoxLayout

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from krx_research.collectors.xing_schema import UnifiedSchemaReadiness, REQUIRED_TRS

class Dialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LS xingAPI 통합 schema readiness")
        self.resize(800,520)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel(
            "4개 최신 RES + 2개 최신 DevCenter schema를 합쳐 6개 필수 TR readiness를 확인합니다."
        ))
        self.text=QTextEdit(); self.text.setReadOnly(True); layout.addWidget(self.text,1)
        b=QPushButton("다시 검사"); b.clicked.connect(self.refresh); layout.addWidget(b)
        self.refresh()

    def refresh(self):
        r=UnifiedSchemaReadiness.discover()
        lines=[
            f"current_res: {r.current_res_dir}",
            f"schemas: {r.schema_dir}",
            "",
        ]
        for tr in REQUIRED_TRS:
            lines.append(f"{tr}: {'READY' if r.tr_ready(tr) else 'NOT READY'}")
        lines += [
            "",
            f"missing: {', '.join(r.missing) if r.missing else '없음'}",
            f"최종 schema readiness: {'READY' if r.ready else 'BLOCKED'}",
        ]
        self.text.setPlainText("\n".join(lines))

def main():
    app=QApplication(sys.argv); d=Dialog(); d.show(); return app.exec()

if __name__=="__main__":
    raise SystemExit(main())
