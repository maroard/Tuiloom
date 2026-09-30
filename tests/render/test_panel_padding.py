import pytest

from tuiloom import KeyBinding, MenuDisplay, ScreenContent, TerminalApp, TerminalMenu
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.screen_content import ContentSize


def make_renderer() -> tuple[TerminalMenu, TerminalRenderer]:
    menu = TerminalMenu(TerminalApp("App"), MenuDisplay("main", "Main"))
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=False
    )
    menu._terminal_renderer = renderer
    return menu, renderer


def test_padding_is_inside_border_and_reduces_responsive_size() -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(
        ScreenContent.responsive(lambda size: f"{size.width}x{size.height}"),
        padding_top=1,
        padding_bottom=1,
        padding_left=2,
        padding_right=3,
    )
    frame = renderer._compose_frame(20, 12)
    menu_height = len(renderer._menu_renderer.render_result(max_width=18).lines)
    panel_height = 12 - menu_height - 2
    assert panel._runtime.effective_size == ContentSize(13, panel_height - 2)
    assert frame[1] == "┊" + " " * 18 + "┊"
    assert frame[2].startswith("┊  ")
    assert frame[2].endswith(" " * 3 + "┊")
    assert frame[panel_height] == "┊" + " " * 18 + "┊"


def test_padding_update_is_partial_and_validated_atomically() -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.static("X"), padding_left=2)
    panel.update_padding(top=1, right=3)
    assert (
        panel.padding_top,
        panel.padding_bottom,
        panel.padding_left,
        panel.padding_right,
    ) == (1, 0, 2, 3)
    with pytest.raises(ValueError):
        panel.update_padding(left=-1)
    with pytest.raises(TypeError):
        panel.update_padding(bottom=True)
    assert (
        panel.padding_top,
        panel.padding_bottom,
        panel.padding_left,
        panel.padding_right,
    ) == (1, 0, 2, 3)
    assert renderer._compose_frame(10, 10) != ["Terminal window is too small."]


def test_padding_that_eliminates_content_uses_too_small_view() -> None:
    menu, renderer = make_renderer()
    menu.add_content_panel(ScreenContent.static("X"), padding_left=8)
    assert renderer._compose_frame(10, 20) == ["Terminal w"]


@pytest.mark.parametrize(
    "content",
    [
        ScreenContent.responsive(lambda size: "text", min_width=30, min_height=12),
        ScreenContent.animated(lambda size, frame: "text", min_width=30, min_height=12),
    ],
)
def test_padding_preserves_generated_content_minimums(content: ScreenContent) -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(content, padding_left=3, padding_top=2)
    renderer._compose_frame(20, 12)
    assert panel._runtime.effective_size == ContentSize(30, 12)
    assert panel._runtime.viewport is not None
    assert panel._runtime.viewport.width == 15


def test_live_padding_update_resizes_viewport() -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.static("content"))
    renderer._compose_frame(20, 12)
    assert panel._runtime.viewport is not None
    initial_width = panel._runtime.viewport.width
    panel.update_padding(left=3)
    renderer._compose_frame(20, 12)
    assert panel._runtime.viewport.width == initial_width - 3


def test_modal_input_removes_panel_focus_border() -> None:
    menu, renderer = make_renderer()
    panel = menu.add_content_panel(ScreenContent.static("content"))
    menu._handle_event(InputEvent(KeyBinding("tab")))
    assert menu.focused_panel is panel
    assert renderer._compose_frame(20, 12)[0].startswith("╭──")
    menu.enter_input_mode("Text: ", lambda text: None)
    assert menu.focused_panel is None
    assert renderer._compose_frame(20, 12)[0].startswith("╭┄┄")
