from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import TYPE_CHECKING

from tuiloom.animation import AnimatedText, AnimationFrame, TextSource
from tuiloom.choice_layout import (
    choice_indent,
    choice_lines,
    choice_slot_width,
    choice_token,
)
from tuiloom.command import MenuChoice
from tuiloom.render.rendered_content import RenderResult
from tuiloom.render.terminal_text import (
    center_display,
    clip_display,
    display_width,
    ljust_display,
    normalize_text_lines,
    wrap_display,
)

if TYPE_CHECKING:
    from tuiloom.terminal_menu import TerminalMenu


@dataclass(frozen=True, slots=True)
class _MenuState:
    """Capture every value affecting the menu box."""

    app_name: str
    title: str
    menu_name: str
    requested_width: int | None
    strict_width: bool
    overlay: bool
    text: str | None
    message: str | None
    commands: tuple[tuple[str, bool], ...]
    choice: tuple[int, MenuChoice, int | None, int | None] | None
    choice_labels: tuple[str, ...] | None
    exit_label: str | None
    selected_index: int
    focus: str
    has_content: bool
    show: bool
    alert: str | None
    alert_prompt: str | None
    input_prompt: str | None
    input_text: str


class MenuRenderer:
    """Build the navigation box for a menu's current state."""

    def __init__(self, menu: TerminalMenu) -> None:
        """Capture a menu and initialize its render cache."""
        self._menu = menu
        self._state: _MenuState | None = None
        self._cached_result: RenderResult | None = None
        self._cached_width: int | None = None
        self._revision = 0
        self._animation_elapsed = 0.0
        self._animated_cache: dict[int, tuple[AnimatedText, int, str]] = {}
        self.update()

    def set_animation_elapsed(self, elapsed: float) -> None:
        """Resolve animated menu text for the current active-time snapshot."""
        self._animation_elapsed = elapsed
        self.update()

    def resolve_text(self, source: TextSource) -> str:
        """Resolve one static or animated string at the current frame index."""
        if not isinstance(source, AnimatedText):
            return source
        index = floor(self._animation_elapsed * source.fps + 1e-9)
        cached = self._animated_cache.get(id(source))
        if cached is not None and cached[0] is source and cached[1] == index:
            return cached[2]
        value = source.renderer(AnimationFrame(self._animation_elapsed, index))
        if not isinstance(value, str):
            raise TypeError("AnimatedText renderer must return a str")
        self._animated_cache[id(source)] = (source, index, value)
        return value

    def animation_rates(self) -> tuple[float, ...]:
        """Return rates of visible animated menu text sources."""
        if not self._menu._menu_box_visible:
            return ()
        return tuple(source.fps for source in self._animated_sources())

    def _animated_sources(self) -> tuple[AnimatedText, ...]:
        """Collect text sources actually visible in the menu box."""
        menu = self._menu
        if not menu._menu_box_visible or menu._task_exit is not None:
            return ()
        sources: list[TextSource | None] = [menu.display_state.title]
        hover_message = menu._hover_message()
        sources.append(
            hover_message if hover_message is not None else menu.display_state.message
        )
        if menu._alert is None:
            sources.append(menu.display_state.text)
            sources.extend(command.label for command in menu.commands)
            active = menu._active_choice()
            if active is not None:
                sources.extend(option.label for option in active.options)
        return tuple(source for source in sources if isinstance(source, AnimatedText))

    def _configured_animated_sources(self) -> tuple[AnimatedText, ...]:
        """Retain frame cache for sources hidden by alerts or menu visibility."""
        menu = self._menu
        sources: list[TextSource | None] = [
            menu.display_state.title,
            menu.display_state.text,
            menu.display_state.message,
            *(command.label for command in menu.commands),
        ]
        for command in menu.commands:
            if isinstance(command, MenuChoice):
                sources.extend(option.label for option in command.options)
        return tuple(source for source in sources if isinstance(source, AnimatedText))

    @property
    def revision(self) -> int:
        """Return the visible-state revision."""
        return self._revision

    @property
    def minimum_width(self) -> int:
        """Return the inner width below which the menu cannot fit."""
        state = self._require_state()
        if state.strict_width and state.requested_width is not None:
            return state.requested_width
        return max(4, state.requested_width or 0)

    @property
    def width(self) -> int:
        """Return the desired inner width before applying terminal limits."""
        state = self._require_state()
        if state.strict_width and state.requested_width is not None:
            return state.requested_width
        requirements = [
            4,
            display_width(state.app_name),
            display_width(state.title),
        ]
        for content in (
            state.text,
            state.message,
            state.alert,
            state.alert_prompt,
            state.input_prompt,
        ):
            if content:
                requirements.extend(
                    display_width(line) + 2 for line in normalize_text_lines(content)
                )
        requirements.extend(
            display_width(f"> {label}" + (" (disabled)" if not enabled else ""))
            for label, enabled in state.commands
        )
        if state.choice is not None:
            _, choice, _, _ = state.choice
            choice_labels = state.choice_labels
            if choice_labels is None:
                raise RuntimeError("Choice labels are missing")
            if choice.vertical:
                requirements.extend(
                    2
                    + max(
                        choice_slot_width(line) for line in normalize_text_lines(label)
                    )
                    for label in choice_labels
                )
            else:
                for row in range(choice.rows):
                    row_labels = [
                        label
                        for option, label in zip(
                            choice.options, choice_labels, strict=True
                        )
                        if option.row == row
                    ]
                    if row_labels:
                        requirements.append(
                            sum(choice_slot_width(label) for label in row_labels)
                            + 2
                            + 2 * (len(row_labels) - 1)
                        )
        if state.exit_label is not None:
            requirements.append(display_width(f"> {state.exit_label}"))
        if state.input_prompt is not None:
            requirements.append(
                display_width(f"{state.input_prompt}{state.input_text}") + 2
            )
        return max(max(requirements), state.requested_width or 0)

    def update(self) -> None:
        """Refresh the cached snapshot from the owning menu."""
        menu = self._menu
        context = menu.display_state
        exit_view = menu._task_exit
        if exit_view is None:
            visible = menu._menu_box_visible
            body_visible = visible and menu._alert is None
            resolve_heading = self.resolve_text if visible else str
            resolve_body = self.resolve_text if body_visible else str
            title = resolve_heading(context.title)
            text = resolve_body(context.text) if context.text is not None else None
            hover_message = menu._hover_message()
            message_source = (
                hover_message if hover_message is not None else context.message
            )
            message = (
                resolve_heading(message_source) if message_source is not None else None
            )
            commands = tuple(
                (resolve_body(command.label), command.enabled)
                for command in menu.commands
            )
            exit_label: str | None = menu._exit_label
            selected_index = menu._selected_index
            alert = menu._alert.text if menu._alert is not None else None
            alert_prompt = menu._alert.prompt if menu._alert is not None else None
            input_prompt = (
                menu._input.prompt
                if menu._input is not None and menu._alert is None
                else None
            )
            active = menu._active_choice()
            choice = (
                (
                    menu._selected_index,
                    active,
                    menu._choice_index,
                    active.selected_index,
                )
                if active is not None
                else None
            )
            choice_labels = (
                tuple(resolve_body(option.label) for option in active.options)
                if active is not None
                else None
            )
        else:
            title = exit_view.visible_title(len(menu._current_exit_panels()))
            text = None
            message = None
            commands = tuple((row, True) for row in exit_view.rows)
            exit_label = None
            selected_index = exit_view.selected_index
            alert = None
            alert_prompt = None
            input_prompt = None
            choice = None
            choice_labels = None
        state = _MenuState(
            app_name=menu.app.name,
            title=title,
            menu_name=context.menu_name,
            requested_width=context.width,
            strict_width=context.strict_width,
            overlay=menu.presentation == "overlay",
            text=text,
            message=message,
            commands=commands,
            choice=choice,
            choice_labels=choice_labels,
            exit_label=exit_label,
            selected_index=selected_index,
            focus="menu" if menu._focused_panel is None else "content",
            has_content=bool(menu._visible_content_panels()),
            show=menu._menu_box_visible,
            alert=alert,
            alert_prompt=alert_prompt,
            input_prompt=input_prompt,
            input_text=menu._display_input_buffer(),
        )
        active_ids = {id(source) for source in self._configured_animated_sources()}
        self._animated_cache = {
            key: value
            for key, value in self._animated_cache.items()
            if key in active_ids
        }
        if state == self._state:
            return
        self._state = state
        self._cached_result = None
        self._revision += 1

    def render(self, *, max_width: int | None = None) -> str:
        """Render with an optional inner limit, preserving the minimum width."""
        return "\n".join(self.render_result(max_width=max_width).lines)

    def render_result(self, *, max_width: int | None = None) -> RenderResult:
        """Return the menu lines together with the cursor on its prompt row."""
        self.update()
        state = self._require_state()
        if not state.show:
            return RenderResult([])
        width = self.effective_width(max_width)
        if self._cached_result is None or self._cached_width != width:
            self._cached_result = self._render_menu(state, width)
            self._cached_width = width
        return self._cached_result

    def effective_width(self, max_width: int | None) -> int:
        """Return the same inner width used by rendering and choice navigation."""
        width = self.width
        if max_width is not None:
            width = max(self.minimum_width, min(width, max_width))
        return width

    def _render_menu(self, state: _MenuState, width: int) -> RenderResult:
        input_cursor = None
        focused = (
            not state.has_content or state.focus == "menu" or state.alert is not None
        )
        horizontal = "─" if focused else "┄"
        vertical = "│" if focused else "┊"
        lines = [
            f"╭{horizontal * width}╮",
            *(
                self._content_row(line, width, vertical, centered=True)
                for line in self._wrapped_lines(state.app_name, width)
            ),
            f"├{horizontal * width}┤",
            *(
                self._content_row(line, width, vertical, centered=True)
                for line in self._wrapped_lines(state.title, width)
            ),
            f"├{horizontal * width}┤",
        ]
        if state.alert is not None:
            lines.extend(self._text_rows(state.alert, width, vertical))
            if state.alert_prompt is not None:
                lines.append(f"{vertical}{'':{width}}{vertical}")
                lines.extend(self._text_rows(state.alert_prompt, width, vertical))
        else:
            if state.text:
                lines.extend(self._text_rows(state.text, width, vertical))
                lines.append(f"{vertical}{'':{width}}{vertical}")
            for index, (label, enabled) in enumerate(state.commands):
                option_cursor = (
                    state.choice is not None
                    and state.choice[0] == index
                    and state.choice[2] is not None
                )
                marker = (
                    ">" if index == state.selected_index and not option_cursor else " "
                )
                suffix = " (disabled)" if not enabled else ""
                lines.extend(
                    self._command_rows(f"{label}{suffix}", marker, width, vertical)
                )
                if state.choice is not None and state.choice[0] == index:
                    _, choice, cursor, selected = state.choice
                    labels = state.choice_labels
                    if labels is None:
                        raise RuntimeError("Choice labels are missing")
                    for visual in choice_lines(choice, width, labels):
                        tokens = []
                        for position, option in enumerate(visual.indices):
                            label = labels[option]
                            token = choice_token(
                                label,
                                selected=selected == option,
                                cursor=cursor == option,
                            )
                            if position < len(visual.indices) - 1:
                                token += " " * (
                                    choice_slot_width(label) - display_width(token)
                                )
                            tokens.append(token)
                        raw = " " * choice_indent(width) + "  ".join(tokens)
                        lines.extend(
                            self._content_row(line, width, vertical)
                            for line in self._wrapped_lines(raw, width)
                        )
            if state.exit_label is not None:
                exit_marker = (
                    ">" if state.selected_index == len(state.commands) else " "
                )
                lines.extend(
                    self._command_rows(state.exit_label, exit_marker, width, vertical)
                )
            if state.input_prompt is not None:
                lines.append(f"{vertical}{'':{width}}{vertical}")
                input_rows = self._text_rows(
                    f"{state.input_prompt}{state.input_text}",
                    width,
                    vertical,
                    drop_whitespace=False,
                )
                lines.extend(input_rows)
                padding = 1 if width >= 4 else 0
                last_input = self._wrapped_lines(
                    f"{state.input_prompt}{state.input_text}",
                    width - 2 * padding,
                    drop_whitespace=False,
                )[-1]
                input_cursor = (
                    len(lines),
                    min(width + 1, 2 + padding + display_width(last_input)),
                )
        if state.message:
            lines.append(f"├{horizontal * width}┤")
            lines.extend(self._text_rows(state.message, width, vertical))
        lines.append(f"╰{horizontal * width}╯")
        return RenderResult(lines, input_cursor)

    @staticmethod
    def _content_row(
        text: str, width: int, vertical: str, *, centered: bool = False
    ) -> str:
        # A grapheme wider than the entire inner area cannot be wrapped to fit.
        clipped = clip_display(text, 0, width)
        align = center_display if centered else ljust_display
        return f"{vertical}{align(clipped, width)}{vertical}"

    @staticmethod
    def _wrapped_lines(
        text: str, width: int, *, drop_whitespace: bool = True
    ) -> list[str]:
        return [
            line
            for raw_line in normalize_text_lines(text)
            for line in wrap_display(raw_line, width, drop_whitespace=drop_whitespace)
        ]

    @staticmethod
    def _command_rows(label: str, marker: str, width: int, vertical: str) -> list[str]:
        if width < 4:
            # Keep wrapping independent of selection: a whitespace marker alone
            # would be dropped, changing the height when selection moves.
            wrapped = MenuRenderer._wrapped_lines(f"> {label}", width)
            wrapped[0] = wrapped[0].replace(">", marker, 1)
            return [
                MenuRenderer._content_row(line, width, vertical) for line in wrapped
            ]
        return [
            MenuRenderer._content_row(
                (f"{marker} " if index == 0 else "  ") + line, width, vertical
            )
            for index, line in enumerate(MenuRenderer._wrapped_lines(label, width - 2))
        ]

    @staticmethod
    def _text_rows(
        text: str, width: int, vertical: str, *, drop_whitespace: bool = True
    ) -> list[str]:
        padding = 1 if width >= 4 else 0
        return [
            MenuRenderer._content_row(" " * padding + line, width, vertical)
            for line in MenuRenderer._wrapped_lines(
                text, width - 2 * padding, drop_whitespace=drop_whitespace
            )
        ]

    def _require_state(self) -> _MenuState:
        if self._state is None:
            raise RuntimeError("Menu renderer has no state")
        return self._state
