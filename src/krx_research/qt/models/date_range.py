from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DateRange:
    """Validated user-selected date interval shared by Qt controllers.

    The model is deliberately UI- and database-free so every screen applies the
    same date ordering rule without duplicating business validation inside a
    QWidget/QMainWindow.
    """

    start: dt.date
    end: dt.date

    def validate(self) -> "DateRange":
        if self.start > self.end:
            raise ValueError(
                f"시작일 {self.start.isoformat()}은 종료일 {self.end.isoformat()}보다 늦을 수 없습니다."
            )
        return self
