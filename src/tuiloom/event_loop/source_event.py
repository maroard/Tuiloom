from dataclasses import dataclass
from types import TracebackType
from typing import Literal

type SourceEventKind = Literal["data", "complete", "error"]


@dataclass(frozen=True, slots=True)
class SourceEvent:
    """Carry one generation-tagged result from a content source worker."""

    generation: int
    kind: SourceEventKind
    value: str | list[str] | None = None
    error: BaseException | None = None
    traceback: TracebackType | None = None
