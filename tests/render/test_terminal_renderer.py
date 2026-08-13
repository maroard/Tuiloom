import os
from io import StringIO

import pytest

import tuiloom.render.terminal_renderer as terminal_renderer_module
from tuiloom.command import CommandContext
from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.rendered_content import RenderedContent
from tuiloom.render.segment_diff import SegmentChange, get_segment_changes
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.render.viewport import Viewport
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


def make_stream_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> TerminalRenderer:
    """Create a renderer whose viewport shows three of many streamed lines."""
    renderer = make_renderer(monkeypatch, StringIO())
    renderer.set_content_renderer(ContentRenderer(iter(())))
    monkeypatch.setattr(
        terminal_renderer_module,
        "get_terminal_size",
        lambda: os.terminal_size((40, 16)),
    )
    return renderer


def fill_and_follow_bottom(
    renderer: TerminalRenderer,
    mode: str,
) -> None:
    """Fill a stream and apply one auto-scroll policy."""
    renderer.content_renderer.append_stream_batch(
        ["1\n2\n3\n4\n5\n6\n7\n8"]
    )
    renderer.apply_stream_auto_scroll(mode)  # type: ignore[arg-type]
    renderer.render()


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


def test_clean_renderer_skips_complete_frame_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_renderer(monkeypatch, StringIO())
    compose_calls = 0
    original = renderer._compose_frame

    def count(
        input_buffer: str,
        terminal_width: int,
        terminal_height: int,
    ) -> list[str]:
        nonlocal compose_calls
        compose_calls += 1
        return original(input_buffer, terminal_width, terminal_height)

    monkeypatch.setattr(renderer, "_compose_frame", count)
    renderer.render()
    renderer.render()

    assert compose_calls == 1


def test_changed_input_writes_only_the_changed_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    renderer.render("1")
    output.seek(0)
    output.truncate()

    renderer.render("12")

    screen = output.getvalue()
    assert "\033[19;17H" in screen
    assert "2" in screen
    assert "Choice?" not in screen


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


def test_invalidated_frame_forces_complete_redraw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    renderer.render("1")
    output.seek(0)
    output.truncate()

    renderer.invalidate()
    renderer.render("1")

    assert output.getvalue().startswith("\033[?25l\033[H\033[J")


def test_setting_content_renderer_resets_viewport_and_frame_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_renderer(monkeypatch, StringIO())
    renderer.render()
    renderer.viewport = Viewport(
        RenderedContent(lines=["old"], width=3, height=1, finished=True),
        width=3,
        height=1,
    )
    new_content_renderer = ContentRenderer(iter(["new"]))

    renderer.set_content_renderer(new_content_renderer)

    assert renderer.content_renderer is new_content_renderer
    assert renderer.viewport is None
    assert renderer._previous_lines is None
    assert renderer._previous_terminal_size is None


def test_two_changed_regions_produce_two_cursor_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    renderer._previous_lines = ["abc DEF ghi JKL"]
    renderer._previous_terminal_size = os.terminal_size((40, 20))

    renderer._write_segment_changes(
        get_segment_changes(
            renderer._previous_lines,
            ["abc XYZ ghi MNO"],
        )
    )

    screen = output.getvalue()
    assert "\033[1;5H" in screen
    assert "\033[1;13H" in screen
    assert "\033[2K" not in screen


def test_cursor_position_uses_visible_ansi_unicode_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_renderer(monkeypatch, StringIO())

    assert renderer._get_cursor_position(["\x1b[31mChoice: 界\x1b[0m"]) == (1, 11)


def test_final_frame_safety_removes_cursor_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_renderer(monkeypatch, StringIO())
    renderer.content_renderer = ContentRenderer("safe\x1b[2Jtext")

    lines = renderer._compose_frame("", 40, 20)

    assert all("\x1b[2J" not in line for line in lines)


def test_full_frame_writer_strips_unsafe_terminal_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)

    renderer._write_full_frame(["safe\x1b[2Jtext"])

    assert "safe" in output.getvalue()
    assert "text" in output.getvalue()
    assert "\x1b[2J" not in output.getvalue()


def test_segment_writer_strips_unsafe_terminal_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)

    renderer._write_segment_changes(
        [SegmentChange(row=1, column=1, content="safe\x1b[2Jtext")]
    )

    assert "safe" in output.getvalue()
    assert "text" in output.getvalue()
    assert "\x1b[2J" not in output.getvalue()


def test_render_restores_cursor_after_styled_wide_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)

    renderer.render("\x1b[31m界\x1b[0m")

    assert output.getvalue().endswith("\033[19;18H\033[?25h")


def test_shorter_segment_erases_only_residual_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    renderer = make_renderer(monkeypatch, output)
    renderer._previous_lines = ["abcdef"]
    renderer._previous_terminal_size = os.terminal_size((40, 20))

    changes = get_segment_changes(["abcdef"], ["abc"])
    renderer._write_segment_changes(changes)

    screen = output.getvalue()
    assert "\033[1;4H" in screen
    assert "\033[3X" in screen
    assert "\033[2K" not in screen


def test_smart_auto_scroll_follows_new_stream_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    renderer.content_renderer.append_stream_batch(["1\n2\n3\n4\n5"])

    renderer.apply_stream_auto_scroll("smart")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.is_at_bottom() is True


def test_strict_auto_scroll_returns_to_bottom_after_manual_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    fill_and_follow_bottom(renderer, "strict")
    renderer.scroll_up()
    renderer.content_renderer.append_stream_batch(["\n9"])

    renderer.apply_stream_auto_scroll("strict")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.is_at_bottom() is True


def test_successful_scroll_up_suspends_smart_auto_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    fill_and_follow_bottom(renderer, "smart")

    renderer.scroll_up()
    preserved_offset = renderer.viewport.offset_y if renderer.viewport else -1
    renderer.content_renderer.append_stream_batch(["\n9"])
    renderer.apply_stream_auto_scroll("smart")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.offset_y == preserved_offset


def test_ineffective_scroll_up_does_not_suspend_smart_auto_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    renderer.scroll_up()
    renderer.content_renderer.append_stream_batch(["1\n2\n3\n4\n5"])

    renderer.apply_stream_auto_scroll("smart")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.is_at_bottom() is True


def test_manual_return_to_bottom_resumes_smart_auto_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    fill_and_follow_bottom(renderer, "smart")
    renderer.scroll_up()

    while renderer.viewport is not None and not renderer.viewport.is_at_bottom():
        renderer.scroll_down()

    renderer.content_renderer.append_stream_batch(["\n9"])
    renderer.apply_stream_auto_scroll("smart")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.is_at_bottom() is True


def test_disabled_auto_scroll_preserves_vertical_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    fill_and_follow_bottom(renderer, "strict")
    renderer.scroll_up()
    preserved_offset = renderer.viewport.offset_y if renderer.viewport else -1
    renderer.content_renderer.append_stream_batch(["\n9"])

    renderer.apply_stream_auto_scroll(None)
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.offset_y == preserved_offset


def test_new_content_renderer_resets_smart_auto_scroll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    fill_and_follow_bottom(renderer, "smart")
    renderer.scroll_up()
    new_content_renderer = ContentRenderer(iter(()))
    new_content_renderer.append_stream_batch(["1\n2\n3\n4\n5"])

    renderer.set_content_renderer(new_content_renderer)
    renderer.apply_stream_auto_scroll("smart")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.is_at_bottom() is True


def test_auto_scroll_preserves_horizontal_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = make_stream_renderer(monkeypatch)
    renderer.content_renderer.append_stream_batch(
        ["abcdefghijk\n2\n3\n4\n5"]
    )
    renderer.render()
    renderer.scroll_right()
    horizontal_offset = renderer.viewport.offset_x if renderer.viewport else -1

    renderer.apply_stream_auto_scroll("strict")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.offset_x == horizontal_offset


def test_auto_scroll_uses_resized_viewport_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_size = [os.terminal_size((40, 18))]
    renderer = make_stream_renderer(monkeypatch)
    monkeypatch.setattr(
        terminal_renderer_module,
        "get_terminal_size",
        lambda: terminal_size[0],
    )
    fill_and_follow_bottom(renderer, "strict")
    terminal_size[0] = os.terminal_size((40, 16))
    renderer.content_renderer.append_stream_batch(["\n9"])

    renderer.apply_stream_auto_scroll("strict")
    renderer.render()

    assert renderer.viewport is not None
    assert renderer.viewport.is_at_bottom() is True
