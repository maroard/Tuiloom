from __future__ import annotations

from collections import UserList

import pytest

import tuiloom
from tuiloom import MenuDisplay, ScreenContent, TerminalApp, TerminalMenu


def make_menu(count: int = 3) -> TerminalMenu:
    menu = TerminalMenu(TerminalApp("App"), MenuDisplay("main", "Main"))
    for index in range(count):
        menu.add_content_panel(ScreenContent.static(str(index)))
    return menu


def test_implicit_layout_is_vertical_and_explicit_layout_keeps_flat_collection() -> (
    None
):
    menu = make_menu()
    a, b, c = menu.content_panels
    assert tuple(row.panels for row in menu.content_layout) == ((a,), (b,), (c,))

    menu.set_content_layout([[b, a], [c]])

    assert all(isinstance(row, tuiloom.ContentRow) for row in menu.content_layout)
    assert tuple(row.panels for row in menu.content_layout) == ((b, a), (c,))
    assert menu.content_panels == (a, b, c)
    assert (a.position, b.position, c.position) == (0, 1, 2)


def test_layout_accepts_sequence_inputs_as_annotated() -> None:
    menu = make_menu(2)
    a, b = menu.content_panels
    menu.set_content_layout(UserList([UserList([a, b])]))
    assert menu.content_layout[0].panels == (a, b)


@pytest.mark.parametrize(
    "layout",
    [[], [[]], [[None]], [["A"]], [[0]]],
)
def test_invalid_structure_does_not_change_layout(layout: object) -> None:
    menu = make_menu(1)
    before = menu.content_layout
    with pytest.raises((TypeError, ValueError)):
        menu.set_content_layout(layout)  # type: ignore[arg-type]
    assert menu.content_layout == before


def test_duplicate_foreign_removed_and_missing_panels_are_rejected_atomically() -> None:
    menu = make_menu()
    a, b, c = menu.content_panels
    foreign = make_menu(1).content_panels[0]
    removed = menu.add_content_panel(ScreenContent.static("removed"))
    removed.remove()
    before = menu.content_layout
    for layout in (
        [[a, b], [b, c]],
        [[a, foreign], [b, c]],
        [[a, removed], [b, c]],
        [[a, b]],
    ):
        with pytest.raises(ValueError):
            menu.set_content_layout(layout)
        assert menu.content_layout == before


def test_row_bounds_and_collapse_settings_must_be_compatible() -> None:
    menu = make_menu(2)
    a, b = menu.content_panels
    a.set_layout(min_height=5)
    b.set_layout(max_height=3)
    with pytest.raises(ValueError, match="height"):
        menu.set_content_layout([[a, b]])
    b.set_layout(max_height=6)
    b.collapse()
    with pytest.raises(ValueError, match="collaps"):
        menu.set_content_layout([[a, b]])


def test_add_and_remove_keep_explicit_layout_exhaustive() -> None:
    menu = make_menu(3)
    a, b, c = menu.content_panels
    menu.set_content_layout([[a, b], [c]])
    d = menu.add_content_panel(ScreenContent.static("new"), position=0)
    assert menu.content_panels == (d, a, b, c)
    assert tuple(row.panels for row in menu.content_layout) == ((a, b), (c,), (d,))
    a.remove()
    c.remove()
    assert tuple(row.panels for row in menu.content_layout) == ((b,), (d,))
    b.remove()
    d.remove()
    assert menu.content_layout == ()


def test_row_collapse_updates_all_members_and_panel_methods_remain_singleton() -> None:
    menu = make_menu()
    a, b, c = menu.content_panels
    menu.set_content_layout([[a, b], [c]])
    row = menu.content_layout[0]
    with pytest.raises(ValueError, match="row"):
        a.collapse()
    with pytest.raises(ValueError, match="row"):
        a.set_collapsed_height(2)
    row.set_collapsed_height(2)
    row.collapse()
    assert row.collapsed and row.collapsed_height == 2
    assert (a.collapsed, b.collapsed) == (True, True)
    assert (a.collapsed_height, b.collapsed_height) == (2, 2)
    row.toggle_collapse()
    assert not a.collapsed and not b.collapsed
    c.collapse()
    assert menu.content_layout[1].collapsed
    menu.set_content_layout([[a, b], [c]])
    with pytest.raises(ValueError, match="row"):
        row.collapse()


def test_panel_sizing_update_rejects_conflicting_row_atomically() -> None:
    menu = make_menu(2)
    a, b = menu.content_panels
    menu.set_content_layout([[a, b]])
    a.set_layout(min_height=5)
    with pytest.raises(ValueError, match="height"):
        b.set_layout(max_height=3)
    assert b.max_height is None


def test_directional_moves_and_swaps_change_layout_but_not_flat_positions() -> None:
    menu = make_menu(5)
    a, b, c, d, e = menu.content_panels
    menu.set_content_layout([[a, b], [c, d], [e]])
    a.move_right()
    assert tuple(row.panels for row in menu.content_layout) == ((b, a), (c, d), (e,))
    a.move_down()
    assert tuple(row.panels for row in menu.content_layout) == ((b,), (c, a, d), (e,))
    a.move_down()
    assert tuple(row.panels for row in menu.content_layout) == ((b,), (c, d), (e, a))
    a.move_left()
    assert menu.content_layout[2].panels == (a, e)
    a.swap_up()
    assert tuple(row.panels for row in menu.content_layout) == ((b,), (a, d), (c, e))
    d.swap_down()
    assert tuple(row.panels for row in menu.content_layout) == ((b,), (a, e), (c, d))
    assert menu.content_panels == (a, b, c, d, e)
    assert tuple(panel.position for panel in menu.content_panels) == (0, 1, 2, 3, 4)


def test_directional_edges_are_noops_and_invalid_move_is_atomic() -> None:
    menu = make_menu(3)
    a, b, c = menu.content_panels
    menu.set_content_layout([[a, b], [c]])
    a.move_left()
    a.move_up()
    b.move_right()
    c.move_down()
    b.swap_down()
    assert tuple(row.panels for row in menu.content_layout) == ((a, b), (c,))
    a.set_layout(min_height=5)
    c.set_layout(max_height=3)
    with pytest.raises(ValueError, match="height"):
        a.move_down()
    assert tuple(row.panels for row in menu.content_layout) == ((a, b), (c,))


def test_focus_uses_row_major_order_and_removed_focus_uses_next_visible_panel() -> None:
    menu = make_menu(3)
    a, b, c = menu.content_panels
    menu.set_content_layout([[b, a], [c]])
    observed = []
    for _ in range(4):
        menu._cycle_focus()
        observed.append(menu._focused_panel)
    assert observed == [b, a, c, None]
    menu._focused_panel = a
    a.remove()
    assert menu._focused_panel is c
