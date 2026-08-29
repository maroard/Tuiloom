from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tuiloom.render.terminal_text import (
    center_display,
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
    text: str | None
    message: str | None
    commands: tuple[tuple[str, bool], ...]
    exit_label: str
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
        self._revision = 0
        self.update()

    @property
    def revision(self) -> int:
        """Return the visible-state revision."""
        return self._revision

    @property
    def width(self) -> int:
        """Return the calculated inner width."""
        state = self._require_state()
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
        requirements.extend(display_width(f"> {label}") for label, _ in state.commands)
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
        state = _MenuState(
            app_name=menu.app.name,
            title=context.title,
            menu_name=context.menu_name,
            requested_width=context.width,
            text=context.text,
            message=context.message,
            commands=tuple(
                (command.label, command.enabled) for command in menu.commands
            ),
            exit_label=menu._exit_label,
            selected_index=menu._selected_index,
            focus="menu" if menu._focused_panel is None else "content",
            has_content=menu._has_content(),
            show=menu.show,
            alert=menu._alert_text,
            alert_prompt=menu._alert_prompt,
            input_prompt=menu._input_prompt if menu._alert_text is None else None,
            input_text=menu._display_input_buffer(),
        )
        if state == self._state:
            return
        self._state = state
        self._cached_render = None
        self._revision += 1

    def render(self) -> str:
        """Return the complete menu box or an empty hidden frame."""
        self.update()
        state = self._require_state()
        if not state.show:
            return ""
        if self._cached_render is None:
            self._cached_render = self._render_menu(state)
        return self._cached_render

    def _render_menu(self, state: _MenuState) -> str:
        width = self.width
        focused = (
            not state.has_content or state.focus == "menu" or state.alert is not None
        )
        horizontal = "─" if focused else "┄"
        vertical = "│" if focused else "┊"
        lines = [
            f"╭{horizontal * width}╮",
            f"{vertical}{center_display(state.app_name, width)}{vertical}",
            f"├{horizontal * width}┤",
            f"{vertical}{center_display(state.title, width)}{vertical}",
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
                marker = ">" if index == state.selected_index else " "
                suffix = " (disabled)" if not enabled else ""
                row = ljust_display(f"{marker} {label}{suffix}", width)
                lines.append(f"{vertical}{row}{vertical}")
            exit_marker = ">" if state.selected_index == len(state.commands) else " "
            exit_row = ljust_display(f"{exit_marker} {state.exit_label}", width)
            lines.append(f"{vertical}{exit_row}{vertical}")
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
    def _text_rows(text: str, width: int, vertical: str) -> list[str]:
        rows: list[str] = []
        for raw_line in normalize_text_lines(text):
            for line in wrap_display(raw_line, max(1, width - 2)):
                rows.append(f"{vertical}{ljust_display(' ' + line, width)}{vertical}")
        return rows or [f"{vertical}{'':{width}}{vertical}"]

    def _require_state(self) -> _MenuState:
        if self._state is None:
            raise RuntimeError("Menu renderer has no state")
        return self._state
