from __future__ import annotations
import os,sys
from pathlib import Path
from PySide6.QtWidgets import QApplication,QDialog,QFormLayout,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QPushButton,QVBoxLayout
class EnvRepository:
 def __init__(self,path: Path): self.path=path
 def save(self,values: dict[str,str]):
  lines=self.path.read_text(encoding="utf-8-sig").splitlines() if self.path.is_file() else []; out=[]; done=set()
  for line in lines:
   key=line.split("=",1)[0].strip() if "=" in line else ""
   if key in values: out.append(f"{key}={values[key]}"); done.add(key)
   else: out.append(line)
  if out and out[-1]!="": out.append("")
  for key,value in values.items():
   if key not in done: out.append(f"{key}={value}")
  tmp=self.path.with_suffix(".tmp"); tmp.write_text("\n".join(out).rstrip()+"\n",encoding="utf-8"); os.replace(tmp,self.path)
class Dialog(QDialog):
 def __init__(self,root: Path):
  super().__init__(); self.root=root; self.repo=EnvRepository(root/".env"); self.setWindowTitle("LS xingAPI 로그인 정보 1회 등록"); self.setMinimumWidth(620)
  self.user=QLineEdit(); self.password=QLineEdit(); self.password.setEchoMode(QLineEdit.Password); self.cert=QLineEdit(); self.cert.setEchoMode(QLineEdit.Password)
  form=QFormLayout(); form.addRow("LS xingAPI 사용자 ID",self.user); form.addRow("로그인 비밀번호",self.password); form.addRow("공동인증서 비밀번호",self.cert)
  save=QPushButton("저장"); cancel=QPushButton("취소"); save.clicked.connect(self.do_save); cancel.clicked.connect(self.reject); buttons=QHBoxLayout(); buttons.addStretch(); buttons.addWidget(save); buttons.addWidget(cancel)
  layout=QVBoxLayout(self); info=QLabel("OPEN API App Key/Secret이 아니라 xingAPI COM 로그인 정보입니다.\n저장 위치: C:\\stock\\.env / 값은 로그에 출력하지 않습니다."); info.setWordWrap(True); layout.addWidget(info); layout.addLayout(form); layout.addLayout(buttons)
 def do_save(self):
  user=self.user.text().strip(); password=self.password.text()
  if not user or not password: QMessageBox.critical(self,"입력 오류","사용자 ID와 로그인 비밀번호가 필요합니다."); return
  self.repo.save({"LS_XING_ID":user,"LS_XING_PASSWORD":password,"LS_XING_CERT_PASSWORD":self.cert.text()}); QMessageBox.information(self,"완료","xingAPI 로그인 정보를 저장했습니다."); self.accept()
def main():
 root=Path(__file__).resolve().parents[1]; app=QApplication(sys.argv); return Dialog(root).exec()
if __name__=="__main__": raise SystemExit(main())
