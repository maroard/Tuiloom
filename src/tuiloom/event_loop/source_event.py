from dataclasses import dataclass
from types import TracebackType
from typing import Literal

from tuiloom.content_panel import ContentPanel

type SourceEventKind = Literal["data", "complete", "error"]


@dataclass(frozen=True, slots=True)
class SourceEvent:
    """Carry one panel- and generation-tagged source-worker result."""

    panel: ContentPanel
    generation: int
    kind: SourceEventKind
    value: str | list[str] | None = None
    error: BaseException | None = None
    traceback: TracebackType | None = None
