from pathlib import Path
import sys
from PySide6.QtWidgets import QApplication,QDialog,QLabel,QPushButton,QTextEdit,QVBoxLayout
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from krx_research.collectors.xing.worker_runtime import Xing32Environment
class D(QDialog):
    def __init__(self):
        super().__init__(); self.resize(720,420); self.setWindowTitle("LS xingAPI 32bit Worker 검사"); l=QVBoxLayout(self); l.addWidget(QLabel("64bit 메인과 분리된 32bit xingAPI 환경을 검사합니다.")); self.t=QTextEdit(); self.t.setReadOnly(True); l.addWidget(self.t,1); b=QPushButton("다시 검사"); b.clicked.connect(self.refresh); l.addWidget(b); self.refresh()
    def refresh(self):
        s=Xing32Environment(ROOT).inspect(); self.t.setPlainText("\n".join([f"메인 Python: {64 if sys.maxsize>2**32 else 32}bit",f"worker: {s.python}",f"worker 아키텍처: {s.bits or '확인 불가'}bit",f"pywin32: {'정상' if s.pywin32 else '없음'}",f"XA_Session COM: {'정상' if s.com_registered else '사용 불가'}",f"최종 상태: {'사용 가능' if s.available else '사용 불가'}",f"상세: {s.detail or '-'}","","정상 구조: PySide6/PostgreSQL 64bit ↔ xingAPI Worker 32bit"]))
def main(): app=QApplication(sys.argv); d=D(); d.show(); return app.exec()
if __name__=="__main__": raise SystemExit(main())
