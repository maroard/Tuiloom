from collections.abc import Callable, Iterator
from typing import Literal

from wcwidth import iter_graphemes, iter_sequences, propagate_sgr

from tuiloom.render.rendered_content import RenderedContent
from tuiloom.render.terminal_text import (
    RESET_SGR,
    display_width,
    normalize_line,
    normalize_text_lines,
    sanitize_terminal_text,
)

# Content may be static text or lines, a text stream, or a refresh callable.
type ContentSource = str | list[str] | Iterator[str] | Callable[[], str | list[str]]
type RendererState = Literal["static", "streaming", "dynamic"]


class _StreamingTextBuffer:
    """Normalize completed stream lines once while retaining a mutable tail."""

    def __init__(self) -> None:
        """Create an empty streaming text buffer."""
        self._completed_lines: list[str] = []
        self._completed_widths: list[int] = []
        self._active_fragments: list[str] = []
        self._active_width = 0
        self._raw_tail = ""
        self._style_prefix = ""

    def append(self, chunks: list[str]) -> tuple[list[str], int]:
        """Append chunks and return current normalized lines and width."""
        incoming = self._raw_tail + "".join(chunks)
        self._raw_tail = ""
        parts = incoming.split("\n")
        active_part = parts.pop()

        for completed_part in parts:
            self._consume_part(completed_part, retain_tail=False)
            self._commit_line()

        self._consume_part(active_part, retain_tail=True)

        return self._render()

    def finish(self) -> tuple[list[str], int]:
        """Return final stream geometry without inventing a trailing line."""
        return self._render()

    def _consume_part(self, part: str, retain_tail: bool) -> None:
        """Normalize stable sequences while retaining an extendable suffix."""
        if not part:
            return

        sequences = list(iter_sequences(part))

        for index, (value, is_sequence) in enumerate(sequences):
            is_last = index == len(sequences) - 1

            if is_sequence:
                if value.startswith("\x1b[") and not value.endswith("m") and is_last:
                    self._raw_tail = value
                    continue

                safe_sequence = sanitize_terminal_text(value)
                if not safe_sequence:
                    continue

                self._active_fragments.append(safe_sequence)
                self._update_style_prefix(safe_sequence)
                continue

            graphemes = list(iter_graphemes(value))

            if retain_tail and is_last and graphemes:
                self._raw_tail = graphemes.pop()

            if graphemes:
                self._append_plain_fragment("".join(graphemes))

    def _append_plain_fragment(self, text: str) -> None:
        """Append one stable plain fragment with cached display width."""
        normalized = normalize_line(text)
        self._active_fragments.append(normalized)
        self._active_width += display_width(normalized)

    def _update_style_prefix(self, sequence: str) -> None:
        """Track the SGR state that must continue onto the next line."""
        next_prefix = propagate_sgr([self._style_prefix + sequence, ""])[1]

        if next_prefix.endswith(RESET_SGR):
            next_prefix = next_prefix[: -len(RESET_SGR)]

        self._style_prefix = next_prefix

    def _commit_line(self) -> None:
        """Commit the active line and carry its current SGR state."""
        if self._raw_tail:
            self._append_plain_fragment(self._raw_tail)
            self._raw_tail = ""

        line = "".join(self._active_fragments)

        if self._style_prefix and not line.endswith(RESET_SGR):
            line += RESET_SGR

        self._completed_lines.append(line)
        self._completed_widths.append(self._active_width)
        self._active_fragments = [self._style_prefix] if self._style_prefix else []
        self._active_width = 0

    def _render(self) -> tuple[list[str], int]:
        """Build the visible line list from committed lines and current tail."""
        lines = self._completed_lines.copy()
        widths = self._completed_widths.copy()

        if self._active_fragments or self._raw_tail or not lines:
            tail = "".join(self._active_fragments)

            if self._raw_tail:
                tail += normalize_line(self._raw_tail)

            if self._style_prefix and not tail.endswith(RESET_SGR):
                tail += RESET_SGR

            lines.append(tail)
            widths.append(self._active_width + display_width(self._raw_tail))

        return lines, max(widths, default=0)


class ContentRenderer:
    """Normalize static, dynamic, or streaming content sources."""

    def __init__(self, source: ContentSource) -> None:
        """Select a rendering strategy for the supplied content source."""
        self.source = source
        self.state: RendererState
        self._stream_buffer: _StreamingTextBuffer | None = None

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
            self._stream_buffer = _StreamingTextBuffer()

        elif callable(source):
            self.state = "dynamic"

        else:
            raise TypeError(
                "Content source must be str, list[str], Iterator[str], "
                "or Callable[[], str | list[str]], "
                f"got {type(source).__name__}"
            )

    def update(self) -> RenderedContent:
        """Return the latest normalized content state."""
        return self.rendered_content

    def _handle_static_state(self) -> RenderedContent:
        """Normalize static content and mark it as finished."""
        if isinstance(self.source, (str, list)):
            self._normalize_content(self.source)

        self.rendered_content.finished = True

        return self.rendered_content

    def append_stream_batch(self, chunks: list[str]) -> None:
        """Append one validated batch and update streaming content once."""
        if self.state != "streaming" or self._stream_buffer is None:
            raise RuntimeError(
                "Cannot append stream chunks to a non-streaming renderer"
            )

        for chunk in chunks:
            if not isinstance(chunk, str):
                raise TypeError(
                    f"Streaming content chunks must be str, got {type(chunk).__name__}"
                )

        if not chunks:
            return

        lines, width = self._stream_buffer.append(chunks)
        self._set_rendered_content(lines, width)
        self.rendered_content.finished = False
        self.rendered_content.revision += 1

    def replace_dynamic_content(self, content: str | list[str]) -> None:
        """Replace dynamic content when its latest value changed."""
        if self.state != "dynamic":
            raise RuntimeError(
                "Cannot replace dynamic content on a non-dynamic renderer"
            )

        previous = (
            self.rendered_content.lines,
            self.rendered_content.width,
            self.rendered_content.height,
        )
        self._normalize_content(content)
        current = (
            self.rendered_content.lines,
            self.rendered_content.width,
            self.rendered_content.height,
        )

        if current != previous:
            self.rendered_content.revision += 1

        self.rendered_content.finished = False

    def finish_stream(self) -> None:
        """Commit the stream tail and mark streaming content complete."""
        if self.state != "streaming" or self._stream_buffer is None:
            raise RuntimeError("Cannot finish a non-streaming renderer")

        lines, width = self._stream_buffer.finish()
        self._set_rendered_content(lines, width)
        self.rendered_content.finished = True

    def _normalize_content(
        self,
        content: str | list[str],
    ) -> None:
        """Normalize text or lines and update the rendered dimensions."""
        if isinstance(content, str):
            self.rendered_content.lines = normalize_text_lines(content)

        elif isinstance(content, list) and all(
            isinstance(element, str) for element in content
        ):
            self.rendered_content.lines = [
                normalize_line(line) for line in content
            ] or [""]

        else:
            raise TypeError(
                f"Content must be str or list[str], got {type(content).__name__}"
            )

        width = max(display_width(line) for line in self.rendered_content.lines)
        self._set_rendered_content(self.rendered_content.lines, width)

    def _set_rendered_content(self, lines: list[str], width: int) -> None:
        """Replace normalized lines and their cached geometry."""
        self.rendered_content.lines = lines
        self.rendered_content.width = width
        self.rendered_content.height = len(lines)
