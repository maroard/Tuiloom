from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from tuiloom.content_panel import ContentPanel

type TaskExitMode = Literal["choice", "waiting"]


@dataclass(slots=True)
class TaskExitState:
    """Store temporary task-exit navigation without mutating screen context."""

    mode: TaskExitMode
    selected_index: int
    previous_focus: ContentPanel | None
    previous_selected_index: int
    wait_started_at: float
    visible_panels: tuple[ContentPanel, ...]
    wait_phase: int = -1

    @property
    def actions(self) -> tuple[TaskExitAction, ...]:
        if self.mode == "choice":
            return (
                TaskExitAction.FORCE_QUIT,
                TaskExitAction.WAIT_AND_QUIT,
                TaskExitAction.CANCEL,
            )
        if self.mode == "waiting":
            return (TaskExitAction.CANCEL,)
        return ()

    @property
    def rows(self) -> tuple[str, ...]:
        """Return display labels independently of the actions they invoke."""
        return tuple(action.label for action in self.actions)

    def visible_title(self, operation_count: int) -> str:
        """Return the count-sensitive temporary menu title."""
        plural = operation_count != 1
        return "Operations in progress" if plural else "Operation in progress"

    def move(self, delta: int) -> None:
        """Move selection with wrapping when the current mode has rows."""
        rows = self.rows
        if rows:
            self.selected_index = (self.selected_index + delta) % len(rows)


class TaskExitAction(StrEnum):
    """Stable exit operations whose identity is independent of their labels."""

    FORCE_QUIT = "force_quit"
    WAIT_AND_QUIT = "wait_and_quit"
    CANCEL = "cancel"

    @property
    def label(self) -> str:
        return _ACTION_LABELS[self]


_ACTION_LABELS = {
    TaskExitAction.FORCE_QUIT: "Force quit",
    TaskExitAction.WAIT_AND_QUIT: "Wait and quit",
    TaskExitAction.CANCEL: "Cancel",
}
