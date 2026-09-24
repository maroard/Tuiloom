from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tuiloom.choice_layout import (
    choice_indent,
    choice_lines,
    choice_slot_width,
    choice_token,
)
from tuiloom.command import MenuChoice
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
    text: str | None
    message: str | None
    commands: tuple[tuple[str, bool], ...]
    choice: tuple[int, MenuChoice, int | None, int] | None
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
        self._cached_render: str | None = None
        self._cached_width: int | None = None
        self._revision = 0
        self.update()

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
            for row in range(choice.rows):
                labels = [
                    option.label for option in choice.options if option.row == row
                ]
                if labels:
                    requirements.append(
                        sum(choice_slot_width(label) for label in labels)
                        + 2
                        + 2 * (len(labels) - 1)
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
        context = menu.screen_context
        exit_view = menu._task_exit
        if exit_view is None:
            title = context.title
            text = context.text
            hover_message = menu._hover_message()
            message = hover_message if hover_message is not None else context.message
            commands = tuple(
                (command.label, command.enabled) for command in menu.commands
            )
            exit_label: str | None = menu._exit_label
            selected_index = menu._selected_index
            alert = menu._alert_text
            alert_prompt = menu._alert_prompt
            input_prompt = menu._input_prompt if menu._alert_text is None else None
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
        state = _MenuState(
            app_name=menu.app.name,
            title=title,
            menu_name=context.menu_name,
            requested_width=context.width,
            strict_width=context.strict_width,
            text=text,
            message=message,
            commands=commands,
            choice=choice,
            exit_label=exit_label,
            selected_index=selected_index,
            focus="menu" if menu._focused_panel is None else "content",
            has_content=bool(menu._visible_content_panels()),
            show=menu.show,
            alert=alert,
            alert_prompt=alert_prompt,
            input_prompt=input_prompt,
            input_text=menu._display_input_buffer(),
        )
        if state == self._state:
            return
        self._state = state
        self._cached_render = None
        self._revision += 1

    def render(self, *, max_width: int | None = None) -> str:
        """Render with an optional inner limit, preserving the minimum width."""
        self.update()
        state = self._require_state()
        if not state.show:
            return ""
        width = self.effective_width(max_width)
        if self._cached_render is None or self._cached_width != width:
            self._cached_render = self._render_menu(state, width)
            self._cached_width = width
        return self._cached_render

    def effective_width(self, max_width: int | None) -> int:
        """Return the same inner width used by rendering and choice navigation."""
        width = self.width
        if max_width is not None:
            width = max(self.minimum_width, min(width, max_width))
        return width

    def _render_menu(self, state: _MenuState, width: int) -> str:
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
                    for visual in choice_lines(choice, width):
                        tokens = []
                        for position, option in enumerate(visual.indices):
                            label = choice.options[option].label
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
                lines.extend(
                    self._text_rows(
                        f"{state.input_prompt}{state.input_text}", width, vertical
                    )
                )
        if state.message:
            lines.append(f"├{horizontal * width}┤")
            lines.extend(self._text_rows(state.message, width, vertical))
        lines.append(f"╰{horizontal * width}╯")
        return "\n".join(lines)

    @staticmethod
    def _content_row(
        text: str, width: int, vertical: str, *, centered: bool = False
    ) -> str:
        # A grapheme wider than the entire inner area cannot be wrapped to fit.
        clipped = clip_display(text, 0, width)
        align = center_display if centered else ljust_display
        return f"{vertical}{align(clipped, width)}{vertical}"

    @staticmethod
    def _wrapped_lines(text: str, width: int) -> list[str]:
        return [
            line
            for raw_line in normalize_text_lines(text)
            for line in wrap_display(raw_line, width)
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
    def _text_rows(text: str, width: int, vertical: str) -> list[str]:
        padding = 1 if width >= 4 else 0
        return [
            MenuRenderer._content_row(" " * padding + line, width, vertical)
            for line in MenuRenderer._wrapped_lines(text, width - 2 * padding)
        ]

    def _require_state(self) -> _MenuState:
        if self._state is None:
            raise RuntimeError("Menu renderer has no state")
        return self._state
