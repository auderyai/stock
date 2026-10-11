from __future__ import annotations

from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from krx_research_nextgen.models.screening import ScreeningResult
from krx_research_nextgen.presentation.screening_table import HEADERS, row_values


class ScreeningExportService:
    def export(self, rows: list[ScreeningResult], path: str) -> None:
        self.export_table(HEADERS, [row_values(row) for row in rows], path, "스크리닝 결과")

    def export_table(self, headers, rows, path: str, sheet_name: str) -> None:
        values = [headers, *rows]
        sheet_rows = []
        for row_number, row in enumerate(values, 1):
            cells = "".join(
                f'<c r="{self._column(column)}{row_number}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                for column, value in enumerate(row, 1)
            )
            sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
        sheet = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/></sheetView></sheetViews>'
            f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
        )
        parts = {
            '[Content_Types].xml': '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
            '_rels/.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
            'xl/workbook.xml': '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="' + escape(sheet_name, {'"': '&quot;'}) + '" sheetId="1" r:id="rId1"/></sheets></workbook>',
            'xl/_rels/workbook.xml.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
            'xl/worksheets/sheet1.xml': sheet,
        }
        with ZipFile(path, "w", ZIP_DEFLATED) as book:
            for name, content in parts.items(): book.writestr(name, content.encode("utf-8"))

    @staticmethod
    def _column(index: int) -> str:
        label = ""
        while index:
            index, remainder = divmod(index - 1, 26); label = chr(65 + remainder) + label
        return label
