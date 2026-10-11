from __future__ import annotations

import os
from pathlib import Path
import sys
from PySide6.QtWidgets import QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout

ROOT = Path(__file__).resolve().parents[1]


class EnvRepository:
    KEYS = ("LS_XING_ID", "LS_XING_PASSWORD", "LS_XING_CERT_PASSWORD")
    def __init__(self, path: Path): self.path = path
    def values(self):
        out = {}
        if self.path.is_file():
            for raw in self.path.read_text(encoding="utf-8-sig").splitlines():
                if "=" in raw and not raw.lstrip().startswith("#"):
                    k,v=raw.split("=",1); out[k.strip()]=v.strip().strip('"').strip("'")
        return out
    def save(self, values):
        lines=self.path.read_text(encoding="utf-8-sig").splitlines() if self.path.is_file() else []
        done=set(); result=[]
        for line in lines:
            key=line.split("=",1)[0].strip() if "=" in line else ""
            if key in values:
                result.append(f"{key}={values[key]}"); done.add(key)
            else: result.append(line)
        if result and result[-1] != "": result.append("")
        for key in self.KEYS:
            if key not in done: result.append(f"{key}={values[key]}")
        tmp=self.path.with_suffix(".env.tmp"); tmp.write_text("\n".join(result).rstrip()+"\n",encoding="utf-8"); os.replace(tmp,self.path)


class Dialog(QDialog):
    def __init__(self):
        super().__init__(); self.setWindowTitle("LS xingAPI 로그인 정보 1회 등록"); self.setMinimumWidth(620)
        self.repo=EnvRepository(ROOT/".env"); old=self.repo.values()
        self.user=QLineEdit(old.get("LS_XING_ID","")); self.password=QLineEdit(); self.cert=QLineEdit()
        self.password.setEchoMode(QLineEdit.Password); self.cert.setEchoMode(QLineEdit.Password)
        form=QFormLayout(); form.addRow("LS ID",self.user); form.addRow("LS 로그인 비밀번호",self.password); form.addRow("공동인증서 비밀번호",self.cert)
        save=QPushButton("저장"); cancel=QPushButton("취소"); save.clicked.connect(self.store); cancel.clicked.connect(self.reject)
        buttons=QHBoxLayout(); buttons.addStretch(1); buttons.addWidget(save); buttons.addWidget(cancel)
        layout=QVBoxLayout(self); layout.addWidget(QLabel(f"저장 위치: {ROOT / '.env'}\nOPEN API App Key가 아니라 xingAPI COM 로그인 정보입니다.")); layout.addLayout(form); layout.addLayout(buttons)
    def store(self):
        if not self.user.text().strip() or not self.password.text().strip(): QMessageBox.critical(self,"입력 오류","LS ID와 로그인 비밀번호는 필수입니다."); return
        self.repo.save({"LS_XING_ID":self.user.text().strip(),"LS_XING_PASSWORD":self.password.text(),"LS_XING_CERT_PASSWORD":self.cert.text()})
        QMessageBox.information(self,"저장 완료","xingAPI 로그인 정보를 저장했습니다. 값은 로그에 출력되지 않습니다."); self.accept()


def main(): app=QApplication(sys.argv); return Dialog().exec()
if __name__=="__main__": raise SystemExit(main())
