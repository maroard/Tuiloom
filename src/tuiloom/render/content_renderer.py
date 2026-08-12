from collections.abc import Callable, Iterator
from typing import Literal

from tuiloom.render.rendered_content import RenderedContent

# Content may be static text or lines, a text stream, or a refresh callable.
type ContentSource = str | list[str] | Iterator[str] | Callable[[], str | list[str]]
type RendererState = Literal["static", "streaming", "dynamic"]


class ContentRenderer:
    """Normalize static, dynamic, or streaming content sources."""

    def __init__(self, source: ContentSource) -> None:
        """Select a rendering strategy for the supplied content source."""
        self.source = source
        self.state: RendererState
        self._update: Callable[[], RenderedContent] | None = None
        self._buffer = ""

        self.rendered_content = RenderedContent(
            lines=[""],
            width=0,
            height=1,
            finished=False,
        )

        if (
            isinstance(source, str)
            or isinstance(source, list)
            and all(isinstance(element, str) for element in source)
        ):
            self.state = "static"
            self._handle_static_state()

        elif isinstance(source, Iterator):
            self.state = "streaming"
            self._update = self._handle_streaming_state

        elif callable(source):
            self.state = "dynamic"
            self._update = self._handle_dynamic_state

        else:
            raise TypeError(
                "Content source must be str, list[str], Iterator[str], "
                "or Callable[[], str | list[str]], "
                f"got {type(source).__name__}"
            )

    def update(self) -> RenderedContent:
        """Return the latest normalized content state."""
        if self._update is not None:
            return self._update()

        return self.rendered_content

    def _handle_static_state(self) -> RenderedContent:
        """Normalize static content and mark it as finished."""
        if isinstance(self.source, (str, list)):
            self._normalize_content(self.source)

        self.rendered_content.finished = True

        return self.rendered_content

    def _handle_streaming_state(self) -> RenderedContent:
        """Consume and normalize the next chunk of streaming content."""
        if not isinstance(self.source, Iterator):
            raise RuntimeError(
                "Invalid renderer state: streaming handler was called "
                "with a non-iterator source"
            )

        try:
            chunk = next(self.source)
            if not isinstance(chunk, str):
                raise TypeError(
                    f"Streaming content chunks must be str, got {type(chunk).__name__}"
                )
            self._buffer += chunk

            self._normalize_content(self._buffer)
            self.rendered_content.finished = False

        except StopIteration:
            self.rendered_content.finished = True

        return self.rendered_content

    def _handle_dynamic_state(self) -> RenderedContent:
        """Call and normalize the dynamic content source."""
        if not callable(self.source):
            raise RuntimeError(
                "Invalid renderer state: dynamic handler was called "
                "with a non-callable source"
            )

        self._normalize_content(self.source())
        self.rendered_content.finished = False

        return self.rendered_content

    def _normalize_content(
        self,
        content: str | list[str],
    ) -> None:
        """Normalize text or lines and update the rendered dimensions."""
        if isinstance(content, str):
            self.rendered_content.lines = content.splitlines() or [""]

        elif isinstance(content, list) and all(
            isinstance(element, str) for element in content
        ):
            self.rendered_content.lines = content or [""]

        else:
            raise TypeError(
                f"Content must be str or list[str], got {type(content).__name__}"
            )

        self.rendered_content.width = max(
            len(line) for line in self.rendered_content.lines
        )
        self.rendered_content.height = len(self.rendered_content.lines)
