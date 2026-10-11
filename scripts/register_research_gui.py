"""PySide6 multi-PDF broker research importer."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox
from import_research_pdf import main as import_pdf

def main():
    import sys
    app=QApplication.instance() or QApplication(sys.argv)
    paths,_=QFileDialog.getOpenFileNames(None,'증권사 리포트 PDF 선택 (여러 개 선택 가능)','','PDF (*.pdf)')
    if not paths:return 0
    failures=[]
    for filename in paths:
        try:import_pdf([filename])
        except Exception as exc:failures.append((Path(filename).name,str(exc)))
    summary=f'선택 {len(paths)}건, 처리 {len(paths)-len(failures)}건, 실패 {len(failures)}건'
    if failures:QMessageBox.critical(None,'증권사 리포트 등록',summary+'\n'+'\n'.join(f'{n}: {w}' for n,w in failures[:5]))
    else:QMessageBox.information(None,'증권사 리포트 등록',summary)
    return 2 if failures else 0
if __name__=='__main__':raise SystemExit(main())
