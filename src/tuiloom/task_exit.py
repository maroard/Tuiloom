from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tuiloom.content_panel import ContentPanel

type TaskExitMode = Literal["choice", "waiting", "stopping"]


@dataclass(slots=True)
class TaskExitView:
    """Store temporary task-exit navigation without mutating screen context."""

    mode: TaskExitMode
    selected_index: int
    previous_focus: ContentPanel | None
    previous_selected_index: int
    wait_started_at: float
    visible_panels: tuple[ContentPanel, ...]
    wait_phase: int = -1

    @property
    def rows(self) -> tuple[str, ...]:
        if self.mode == "choice":
            return ("Force quit", "Wait and quit", "Cancel")
        if self.mode == "waiting":
            return ("Cancel",)
        return ()

    def visible_title(self, operation_count: int) -> str:
        """Return a mode- and count-sensitive temporary menu title."""
        plural = operation_count != 1
        if self.mode == "stopping":
            return "Stopping operations..." if plural else "Stopping operation..."
        return "Operations in progress" if plural else "Operation in progress"

    def move(self, delta: int) -> None:
        """Move selection with wrapping when the current mode has rows."""
        rows = self.rows
        if rows:
            self.selected_index = (self.selected_index + delta) % len(rows)
