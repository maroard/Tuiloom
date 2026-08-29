from typing import Protocol


class BackgroundWork(Protocol):
    """Describe native-backed work that must stop before terminal teardown."""

    @property
    def description(self) -> str:
        """Return the text identifying the work to the user."""
        ...

    def cancel(self) -> None:
        """Request cooperative cancellation and discard future output."""
        ...

    def is_alive(self) -> bool:
        """Return whether the underlying worker is still executing."""
        ...

    def join(self, timeout: float | None = None) -> bool:
        """Wait for the underlying worker and report whether it stopped."""
        ...
