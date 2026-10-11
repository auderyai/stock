from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class WorkstationState:
    """Mutable presentation state; no QWidget or database behavior belongs here."""
    current_dataset: Any | None = None
    busy: bool = False
    active_chart_ticker: str | None = None
    child_windows: list[Any] = field(default_factory=list)
