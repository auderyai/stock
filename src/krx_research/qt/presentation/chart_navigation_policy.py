from __future__ import annotations

import pandas as pd

from krx_research.qt.presentation.table_policy import TablePresentationPolicy


class ChartNavigationPresentationPolicy(TablePresentationPolicy):
    """Presentation policy for the result list embedded in a chart window.

    Chart navigation needs only stock-identification and screening-result columns.
    Reference dates remain in the underlying screening data but are deliberately
    hidden from the chart view to avoid redundant date information.
    """

    def prepare(self, frame: pd.DataFrame | None) -> pd.DataFrame:
        prepared = super().prepare(frame)
        date_columns = [column for column in self.date_reference_columns if column in prepared.columns]
        return prepared.drop(columns=date_columns, errors="ignore") if date_columns else prepared


CHART_NAVIGATION_TABLE_POLICY = ChartNavigationPresentationPolicy()
