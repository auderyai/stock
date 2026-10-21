from __future__ import annotations

from collections import defaultdict
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from krx_research_nextgen.models.screening import RepeatedScreenResult, ScreeningResult
from krx_research_nextgen.presentation.repeated_screen_table import (
    HEADERS as REPEATED_HEADERS,
    row_values as repeated_row_values,
)
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
        self._write_workbook(path, sheet_name, sheet)

    def export_repeated(
        self,
        rows: list[RepeatedScreenResult],
        path: str,
        *,
        layout: str = "detailed",
    ) -> None:
        if layout == "detailed":
            self.export_table(
                REPEATED_HEADERS,
                [repeated_row_values(row) for row in rows],
                path,
                "기간 내 다빈도 종목",
            )
            return
        if layout != "frequency_groups":
            raise ValueError(f"지원하지 않는 다빈도 종목 출력 형식입니다: {layout}")
        self._export_repeated_frequency_groups(rows, path)

    def _export_repeated_frequency_groups(
        self,
        rows: list[RepeatedScreenResult],
        path: str,
    ) -> None:
        grouped: dict[int, list[RepeatedScreenResult]] = defaultdict(list)
        for row in rows:
            if row.appearance_count >= 2:
                grouped[row.appearance_count].append(row)

        counts = sorted(grouped, reverse=True)
        for count in counts:
            grouped[count].sort(key=lambda row: (row.stock_name, row.stock_code))

        column_count = 1 + len(counts) * 2
        maximum_rows = max((len(grouped[count]) for count in counts), default=0)
        values: list[list[str | None]] = []
        first_header: list[str | None] = ["횟수"]
        second_header: list[str | None] = [None]
        for count in counts:
            first_header.extend((f"{count}TH", None))
            second_header.extend(("종목명", "업종"))
        values.extend((first_header, second_header))
        for index in range(maximum_rows):
            row_values: list[str | None] = [None]
            for count in counts:
                if index < len(grouped[count]):
                    item = grouped[count][index]
                    row_values.extend((item.stock_name, item.industry))
                else:
                    row_values.extend((None, None))
            values.append(row_values)

        sheet_rows = []
        for row_number, row in enumerate(values, 1):
            cells = []
            for column, value in enumerate(row, 1):
                if value is None:
                    continue
                reference = f"{self._column(column)}{row_number}"
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                )
            sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

        columns = ['<col min="1" max="1" width="10" customWidth="1"/>']
        merges = ['<mergeCell ref="A1:A2"/>']
        for index in range(len(counts)):
            name_column = 2 + index * 2
            industry_column = name_column + 1
            columns.append(
                f'<col min="{name_column}" max="{name_column}" width="20" customWidth="1"/>'
            )
            columns.append(
                f'<col min="{industry_column}" max="{industry_column}" width="30" customWidth="1"/>'
            )
            merges.append(
                f'<mergeCell ref="{self._column(name_column)}1:{self._column(industry_column)}1"/>'
            )

        dimension = f"A1:{self._column(max(column_count, 1))}{max(len(values), 2)}"
        sheet = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="{dimension}"/>'
            '<sheetViews><sheetView workbookViewId="0">'
            '<pane xSplit="1" ySplit="2" topLeftCell="B3" activePane="bottomRight" state="frozen"/>'
            '</sheetView></sheetViews>'
            f'<cols>{"".join(columns)}</cols>'
            f'<sheetData>{"".join(sheet_rows)}</sheetData>'
            f'<mergeCells count="{len(merges)}">{"".join(merges)}</mergeCells>'
            '</worksheet>'
        )
        self._write_workbook(path, "기간 내 다빈도 종목", sheet)

    @staticmethod
    def _write_workbook(path: str, sheet_name: str, sheet: str) -> None:
        parts = {
            '[Content_Types].xml': '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
            '_rels/.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
            'xl/workbook.xml': '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="' + escape(sheet_name, {'"': '&quot;'}) + '" sheetId="1" r:id="rId1"/></sheets></workbook>',
            'xl/_rels/workbook.xml.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
            'xl/worksheets/sheet1.xml': sheet,
        }
        with ZipFile(path, "w", ZIP_DEFLATED) as book:
            for name, content in parts.items():
                book.writestr(name, content.encode("utf-8"))

    @staticmethod
    def _column(index: int) -> str:
        label = ""
        while index:
            index, remainder = divmod(index - 1, 26); label = chr(65 + remainder) + label
        return label
