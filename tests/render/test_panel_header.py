import re

from tuiloom import (
    MenuDisplay,
    ScreenContent,
    SelectableItem,
    TerminalApp,
    TerminalMenu,
    style,
)
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_panel_header_stays_centered_and_fixed_when_content_scrolls() -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"), presentation="overlay")
    menu.hide_menu()
    panel = menu.add_content_panel(
        ScreenContent.selectable(
            [SelectableItem(f"Movement {index}") for index in range(20)]
        ),
        header=style("Turn 1:", bold=True),
    )
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=True
    )

    frame = renderer._compose_frame(32, 12)
    assert plain(frame[1]) == "│" + "Turn 1:".center(30) + "│"
    assert frame[2] == "│" + "─" * 30 + "│"
    assert "\x1b[1mTurn 1:" in frame[1]
    viewport = panel._runtime.viewport
    assert viewport is not None and viewport.height == 8

    viewport.scroll_down()
    scrolled = renderer._compose_frame(32, 12)
    assert scrolled[1:3] == frame[1:3]

    panel.set_header(style("Turn 2:", bold=True))
    updated = renderer._compose_frame(42, 12)
    assert plain(updated[1]) == "│" + "Turn 2:".center(40) + "│"
    assert updated[2] == "│" + "─" * 40 + "│"


def test_header_keeps_one_content_row_or_shows_too_small_view() -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"), presentation="overlay")
    menu.hide_menu()
    menu.add_content_panel(ScreenContent.static("Body"), header="Turn 1:")
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=True
    )

    assert "Terminal window is too small." in "".join(renderer._compose_frame(32, 4))
    assert "Body" in "".join(renderer._compose_frame(32, 5))


def test_header_keeps_configured_body_height_bounds() -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"), presentation="overlay")
    menu.hide_menu()
    panel = menu.add_content_panel(
        ScreenContent.static("Body"),
        header="Turn 1:",
        min_height=3,
        max_height=3,
    )
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=True
    )

    assert "Terminal window is too small." in "".join(renderer._compose_frame(32, 6))
    assert "Body" in "".join(renderer._compose_frame(32, 7))
    assert panel._runtime.viewport is not None
    assert panel._runtime.viewport.height == 3
