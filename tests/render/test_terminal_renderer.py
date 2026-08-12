import os
from io import StringIO

import pytest

import tuiloom.render.terminal_renderer as terminal_renderer_module
from tuiloom.command import CommandContext
from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.screen_context.screen_context import ScreenContext


def do_nothing(context: CommandContext) -> None:
    """Provide a command behavior for renderer tests."""


def make_renderer(
    monkeypatch: pytest.MonkeyPatch,
    output: StringIO,
) -> TerminalRenderer:
    context = ScreenContext(
        app_name="App",
        menu_name="Menu",
        title="Menu",
        commands={
            "0": (do_nothing, "Back"),
            "1": (do_nothing, "One"),
        },
    )
    renderer = TerminalRenderer(
        menu_renderer=MenuRenderer(context),
        content_renderer=ContentRenderer("content"),
        spacing=1,
    )

    monkeypatch.setattr(terminal_renderer_module, "stdout", output)
    monkeypatch.setattr(
        terminal_renderer_module,
        "get_terminal_size",
        lambda: os.terminal_size((40, 20)),
    )

    return renderer


def test_first_render_draws_full_frame_and_positions_input_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)

    renderer.render("12")

    screen = output.getvalue()
    assert screen.startswith("\033[?25l\033[H\033[J")
    assert "Choice? (0-1): 12" in screen
    assert screen.endswith("\033[19;18H\033[?25h")


def test_unchanged_frame_produces_no_additional_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    renderer.render("1")
    output.seek(0)
    output.truncate()

    renderer.render("1")

    assert output.getvalue() == ""


def test_changed_input_rewrites_only_the_prompt_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    renderer.render("1")
    output.seek(0)
    output.truncate()

    renderer.render("12")

    assert output.getvalue() == (
        "\033[?25l\033[19;1H\033[2KChoice? (0-1): 12\033[19;18H\033[?25h"
    )


def test_resize_forces_complete_redraw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    current_size = [os.terminal_size((40, 20))]
    monkeypatch.setattr(
        terminal_renderer_module,
        "get_terminal_size",
        lambda: current_size[0],
    )
    renderer.render("1")
    output.seek(0)
    output.truncate()

    current_size[0] = os.terminal_size((50, 22))
    renderer.render("1")

    assert output.getvalue().startswith("\033[?25l\033[H\033[J")
