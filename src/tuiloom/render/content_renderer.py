"""Normalize the explicit variants of :class:`ScreenContent`."""

from typing import Literal

from wcwidth import iter_graphemes, iter_sequences

from tuiloom.render.rendered_content import RenderedContent
from tuiloom.render.terminal_text import (
    CLOSE_HYPERLINK,
    RESET_SGR,
    display_width,
    expand_tabs,
    hyperlink_continuation,
    normalize_line,
    normalize_text_lines,
    sanitize_terminal_text,
    sgr_continuation,
)
from tuiloom.screen_content import ScreenContent

type RendererState = Literal["static", "streaming", "dynamic", "responsive", "animated"]


class _StreamingTextBuffer:
    """Normalize completed stream lines once while retaining a mutable tail."""

    def __init__(self) -> None:
        """Create an empty streaming text buffer."""
        self._completed_lines: list[str] = []
        self._completed_max_width = 0
        self._active_fragments: list[str] = []
        self._active_width = 0
        self._active_has_content = False
        self._raw_tail = ""
        self._sequence_tail = ""
        self._style_prefix = ""
        self._hyperlink_prefix = ""
        self._active_has_sgr = False
        self._pending_carriage_return = False

    def append(self, chunks: list[str]) -> tuple[list[str], int]:
        """Append chunks and return current normalized lines and width."""
        chunk_text = self._take_stable_text(self._sequence_tail + "".join(chunks))

        if self._pending_carriage_return and not chunk_text:
            return self._render()

        if self._pending_carriage_return:
            if chunk_text.startswith("\n"):
                incoming = self._raw_tail + chunk_text
            else:
                incoming = self._raw_tail + "\r" + chunk_text
            self._pending_carriage_return = False
        else:
            incoming = self._raw_tail + chunk_text

        self._raw_tail = ""

        if incoming.endswith("\r"):
            incoming = incoming[:-1]
            self._pending_carriage_return = True

        incoming = incoming.replace("\r\n", "\n")
        parts = incoming.split("\n")
        active_part = parts.pop()

        for completed_part in parts:
            self._consume_progress_part(completed_part, retain_tail=False)
            self._commit_line()

        self._consume_progress_part(active_part, retain_tail=True)

        return self._render()

    def finish(self) -> tuple[list[str], int]:
        """Return final stream geometry without inventing a trailing line."""
        return self._render()

    def _take_stable_text(self, text: str) -> str:
        """Retain incomplete escapes and sanitize complete terminal tokens."""
        self._sequence_tail = ""
        stable: list[str] = []
        position = 0
        while position < len(text):
            escape = text.find("\x1b", position)
            if escape < 0:
                stable.append(text[position:])
                break
            stable.append(text[position:escape])
            end = self._sequence_end(text, escape)
            if end is None:
                self._sequence_tail = text[escape:]
                break
            stable.append(sanitize_terminal_text(text[escape:end]))
            position = end
        return "".join(stable)

    @staticmethod
    def _sequence_end(text: str, start: int) -> int | None:
        """Find a complete CSI, control string, or ordinary ESC sequence."""
        position = start + 1
        if position == len(text):
            return None
        introducer = text[position]
        position += 1
        if introducer in "]PX^_":
            while position < len(text):
                if text.startswith("\x1b\\", position):
                    return position + 2
                if introducer == "]" and text[position] == "\x07":
                    return position + 1
                position += 1
            return None
        if introducer == "[":
            while position < len(text):
                character = text[position]
                if "@" <= character <= "~":
                    return position + 1
                if not " " <= character <= "?":
                    # An invalid CSI ends before the next ordinary character.
                    return position
                position += 1
            return None
        if " " <= introducer <= "/":
            while position < len(text) and " " <= text[position] <= "/":
                position += 1
            return position + 1 if position < len(text) else None
        return position

    def _consume_progress_part(self, part: str, retain_tail: bool) -> None:
        """Consume text while treating carriage returns as line replacement."""
        segments = part.split("\r")

        for index, segment in enumerate(segments):
            if index:
                self._reset_active_line()

            self._consume_part(
                segment,
                retain_tail=retain_tail and index == len(segments) - 1,
            )

    def _reset_active_line(self) -> None:
        """Discard the unfinished line before a carriage-return rewrite."""
        self._active_fragments = []
        self._active_width = 0
        self._active_has_content = False
        self._raw_tail = ""
        self._style_prefix = ""
        self._hyperlink_prefix = ""
        self._active_has_sgr = False

    def _consume_part(self, part: str, retain_tail: bool) -> None:
        """Normalize stable sequences while retaining an extendable suffix."""
        if not part:
            return
        safe = sanitize_terminal_text(part)
        if retain_tail:
            stable, self._raw_tail = self._split_grapheme_tail(safe)
        else:
            stable = safe
        if stable:
            self._append_fragment(stable)

    @staticmethod
    def _split_grapheme_tail(text: str) -> tuple[str, str]:
        """Retain the last grapheme, including styles embedded in its characters."""
        if "\x1b" not in text:
            graphemes = list(iter_graphemes(text))
            tail = graphemes[-1] if graphemes else ""
            return (text[: -len(tail)], tail) if tail else (text, "")
        plain: list[str] = []
        positions: list[int] = []
        position = 0
        for value, is_sequence in iter_sequences(text):
            if not is_sequence:
                plain.append(value)
                positions.extend(range(position, position + len(value)))
            position += len(value)
        visible = "".join(plain)
        graphemes = list(iter_graphemes(visible))
        if not graphemes:
            return text, ""
        boundary = positions[len(visible) - len(graphemes[-1])]
        return text[:boundary], text[boundary:]

    def _append_fragment(self, text: str) -> None:
        """Append one stable styled fragment with cached display width."""
        normalized = expand_tabs(text, self._active_width)
        if "\x1b" not in normalized:
            normalized = normalize_line(normalized)
        self._active_fragments.append(normalized)
        self._active_has_content = True
        self._active_width += display_width(normalized)
        for value, is_sequence in iter_sequences(text):
            if is_sequence:
                self._update_style_prefix(value)

    def _update_style_prefix(self, sequence: str) -> None:
        """Track the SGR and hyperlink state continued onto the next line."""
        if not sequence.startswith("\x1b["):
            self._hyperlink_prefix = hyperlink_continuation(
                sequence, self._hyperlink_prefix
            )
            return
        self._active_has_sgr = True
        self._style_prefix = sgr_continuation(sequence, self._style_prefix)

    def _commit_line(self) -> None:
        """Commit the active line and carry its current SGR state."""
        if self._raw_tail:
            self._append_fragment(self._raw_tail)
            self._raw_tail = ""

        line = self._close_line("".join(self._active_fragments))

        self._completed_lines.append(line)
        self._completed_max_width = max(self._completed_max_width, self._active_width)
        prefix = self._hyperlink_prefix + self._style_prefix
        self._active_fragments = [prefix] if prefix else []
        self._active_has_sgr = bool(self._style_prefix)
        self._active_width = 0
        self._active_has_content = False

    def _close_line(self, line: str, tail: str = "") -> str:
        """Close active terminal styles without reparsing the growing line."""
        hyperlink = hyperlink_continuation(tail, self._hyperlink_prefix)
        has_sgr = self._active_has_sgr or "\x1b[" in tail
        if hyperlink:
            line += CLOSE_HYPERLINK
        if has_sgr and not line.endswith(RESET_SGR):
            line += RESET_SGR
        return line

    def _render(self) -> tuple[list[str], int]:
        """Build the visible line list from committed lines and current tail."""
        lines = self._completed_lines.copy()
        width = self._completed_max_width

        if self._active_has_content or self._raw_tail or not lines:
            tail = "".join(self._active_fragments)

            visible_tail = expand_tabs(self._raw_tail, self._active_width)
            if "\x1b" not in visible_tail:
                visible_tail = normalize_line(visible_tail)
            tail += visible_tail
            lines.append(self._close_line(tail, self._raw_tail))
            width = max(width, self._active_width + display_width(visible_tail))

        return lines, width


class ContentRenderer:
    """Normalize one explicitly classified screen-content configuration."""

    def __init__(self, content: ScreenContent) -> None:
        """Select the rendering strategy declared by ``content``."""
        if not isinstance(content, ScreenContent):
            raise TypeError("ContentRenderer requires a ScreenContent")
        self.content = content
        self.state: RendererState
        self._stream_buffer: _StreamingTextBuffer | None = None

        self.rendered_content = RenderedContent(
            lines=[""],
            width=0,
            height=1,
            finished=False,
        )

        if content._kind in ("static", "lines"):
            self.state = "static"
            self._handle_static_state()
        elif content._kind == "stream":
            self.state = "streaming"
            self._stream_buffer = _StreamingTextBuffer()
        elif content._kind == "dynamic":
            self.state = "dynamic"
        elif content._kind == "responsive":
            self.state = "responsive"
        elif content._kind == "animated":
            self.state = "animated"
        else:
            raise RuntimeError(f"Unknown ScreenContent kind: {content._kind}")

    def update(self) -> RenderedContent:
        """Return the latest normalized content state."""
        return self.rendered_content

    def _handle_static_state(self) -> RenderedContent:
        """Normalize static content and mark it as finished."""
        self._normalize_content(self.content._static_value())

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

    def replace_generated_content(self, content: str | list[str]) -> None:
        """Replace dynamic, responsive, or animated content when its value changed."""
        if self.state not in ("dynamic", "responsive", "animated"):
            raise RuntimeError("Cannot replace generated content on this renderer")

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

    def replace_dynamic_content(self, content: str | list[str]) -> None:
        """Replace dynamic content (internal compatibility helper)."""
        if self.state != "dynamic":
            raise RuntimeError(
                "Cannot replace dynamic content on a non-dynamic renderer"
            )
        self.replace_generated_content(content)

    def finish_stream(self) -> None:
        """Commit the stream tail and mark streaming content complete."""
        if self.state != "streaming" or self._stream_buffer is None:
            raise RuntimeError("Cannot finish a non-streaming renderer")

        lines, width = self._stream_buffer.finish()
        self._set_rendered_content(lines, width)
        self.rendered_content.finished = True

    def _normalize_content(
        self,
        content: str | list[str] | tuple[str, ...],
    ) -> None:
        """Normalize text or lines and update the rendered dimensions."""
        if isinstance(content, str):
            self.rendered_content.lines = normalize_text_lines(content)

        elif isinstance(content, (list, tuple)) and all(
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
