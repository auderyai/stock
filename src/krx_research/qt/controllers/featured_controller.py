from __future__ import annotations
from datetime import date
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDialog, QMessageBox
from krx_research.qt.chart_window import ChartWindow
from krx_research.qt.presentation.error_presenter import user_friendly_error
from krx_research.qt.services.ports import ErrorLogPort
from krx_research.qt.workers.task_runner import TaskRunner


class FeaturedResearchController(QObject):
    def __init__(self, view, service, chart_data, error_log: ErrorLogPort, parent=None):
        super().__init__(parent or view); self.view=view; self.service=service; self.chart_data=chart_data; self.runner=TaskRunner(self); self.logs=error_log; self.children=[]
        view.queryRequested.connect(self.query); view.repeatedRequested.connect(self.repeated); view.refreshRequested.connect(self.refresh); view.importRequested.connect(self.import_images); view.chartRequested.connect(self.open_chart)
    def initialize(self):
        try: d=self.service.latest_date() or date.today(); self.view.set_date(d); self.query(d,d) if self.service.latest_date() else None
        except Exception as exc: QMessageBox.warning(self.view,"초기화",str(exc))
    def _run(self,fn,on_result): self.runner.submit(fn,on_result=on_result,on_error=self._error)
    def query(self,a,b): self._run(lambda:self.service.query(a,b),lambda f:self.view.set_frame(f,f"{a} ~ {b}: {len(f):,}건"))
    def repeated(self,a,b): self._run(lambda:self.service.repeated(a,b),lambda f:self.view.set_frame(f,f"중복 종목 {len(f):,}건"))
    def refresh(self,a,b):
        def done(result): QMessageBox.information(self.view,"완료",str(result)); self.query(a,b)
        self._run(lambda:self.service.refresh_missing(a,b),done)
    def import_images(self,files):
        def prepared(plan):
            if self.view.confirm_images(plan) != QDialog.Accepted: return
            self._run(lambda:self.service.commit_images(plan),done)
        def done(result):
            dates=", ".join(value.isoformat() for value in result.dates)
            QMessageBox.information(self.view,"등록 완료",f"{dates} · {result.row_count:,}건 등록\nDB 일치 {result.matched_count:,}건 · 미확인 {result.unmatched_count:,}건")
            a,b=self.view.period(); self.query(a,b)
        report_date=self.view.registration_date()
        self._run(lambda:self.service.prepare_images(files,report_date),prepared)
    def open_chart(self,ticker):
        w=ChartWindow(self.chart_data,ticker,parent=self.view); self.children.append(w); w.destroyed.connect(lambda _=None,x=w:self.children.remove(x) if x in self.children else None); w.show()
    def _error(self,trace):
        path=self.logs.write(trace); msg=user_friendly_error(trace); msg += f"\n\n오류 로그: {path}" if path else ""; QMessageBox.critical(self.view,"오류",msg)
