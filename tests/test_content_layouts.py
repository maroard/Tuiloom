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


def test_vertical_span_uses_one_panel_and_one_focus_stop() -> None:
    menu = make_menu()
    graph, output, info = menu.content_panels
    menu.set_content_layout([[graph, output], [graph, info]])

    assert tuple(row.panels for row in menu.content_layout) == (
        (graph, output),
        (graph, info),
    )
    assert menu._visible_content_panels() == (graph, output, info)
    assert menu.content_panels == (graph, output, info)
    visited = []
    for _ in range(4):
        menu._cycle_focus()
        visited.append(menu.focused_panel)
    assert visited == [
        graph,
        output,
        info,
        None,
    ]


def test_vertical_span_rejects_misaligned_or_overlapping_repetitions_atomically() -> (
    None
):
    menu = make_menu(4)
    graph, output, info, extra = menu.content_panels
    before = menu.content_layout
    for layout in (
        [[graph, output], [info, graph], [extra]],
        [[graph, output], [info], [graph, extra]],
        [[graph, output], [graph, output], [info, extra]],
        [[graph, output], [graph, info, extra]],
        [[graph, graph], [output, info, extra]],
    ):
        with pytest.raises(ValueError):
            menu.set_content_layout(layout)
        assert menu.content_layout == before


def test_vertical_span_disallows_row_collapse_and_directional_moves() -> None:
    menu = make_menu()
    graph, output, info = menu.content_panels
    menu.set_content_layout([[graph, output], [graph, info]])
    before = menu.content_layout

    for row in menu.content_layout:
        with pytest.raises(ValueError, match="span"):
            row.collapse()
        with pytest.raises(ValueError, match="span"):
            row.set_collapsed_height(2)
    with pytest.raises(ValueError, match="span"):
        graph.collapse()
    with pytest.raises(ValueError, match="span"):
        output.move_down()
    with pytest.raises(ValueError, match="span"):
        info.swap_up()
    assert menu.content_layout == before


def test_removing_panel_dissolves_incomplete_vertical_span() -> None:
    menu = make_menu()
    graph, output, info = menu.content_panels
    menu.set_content_layout([[graph, output], [graph, info]])
    output.remove()
    assert tuple(row.panels for row in menu.content_layout) == ((graph,), (info,))
    assert menu._visible_content_panels() == (graph, info)


def test_vertical_span_bounds_are_checked_across_its_full_height() -> None:
    menu = make_menu()
    graph, output, info = menu.content_panels
    graph.set_layout(min_height=10)
    output.set_layout(max_height=3)
    info.set_layout(max_height=3)
    before = menu.content_layout
    with pytest.raises(ValueError, match="height"):
        menu.set_content_layout([[graph, output], [graph, info]])
    assert menu.content_layout == before

    graph.set_layout(min_height=1, max_height=5)
    menu.set_content_layout([[graph, output], [graph, info]])
    with pytest.raises(ValueError, match="height"):
        graph.set_layout(min_height=9, max_height=None)
    assert graph.min_height == 1
    with pytest.raises(ValueError, match="height"):
        graph.set_layout(max_height=2)
    assert graph.max_height == 5


def test_vertical_span_rejects_collapsed_members_and_keeps_added_row() -> None:
    menu = make_menu()
    graph, output, info = menu.content_panels
    output.collapse()
    with pytest.raises(ValueError, match="collaps"):
        menu.set_content_layout([[graph, output], [graph, info]])
    output.expand()
    menu.set_content_layout([[graph, output], [graph, info]])
    extra = menu.add_content_panel(ScreenContent.static("extra"))
    assert tuple(row.panels for row in menu.content_layout) == (
        (graph, output),
        (graph, info),
        (extra,),
    )


def test_removing_spanning_panel_keeps_other_panels_in_rows() -> None:
    menu = make_menu()
    graph, output, info = menu.content_panels
    menu.set_content_layout([[graph, output], [graph, info]])
    graph.remove()
    assert tuple(row.panels for row in menu.content_layout) == ((output,), (info,))


def test_removal_dissolves_only_the_affected_span() -> None:
    menu = make_menu(6)
    graph, output, info, second_graph, second_output, second_info = menu.content_panels
    menu.set_content_layout(
        [
            [graph, output],
            [graph, info],
            [second_graph, second_output],
            [second_graph, second_info],
        ]
    )
    unaffected_row = menu.content_layout[2]
    output.remove()
    assert tuple(row.panels for row in menu.content_layout) == (
        (graph,),
        (info,),
        (second_graph, second_output),
        (second_graph, second_info),
    )
    assert menu.content_layout[2] is unaffected_row


def test_removal_with_new_row_bound_conflict_preserves_menu_consistency() -> None:
    menu = make_menu(3)
    graph, output, info = menu.content_panels
    graph.set_layout(min_height=4)
    output.set_layout(max_height=1)
    info.set_layout(max_height=1)
    menu.set_content_layout([[graph, output], [graph, info]])

    info.remove()

    assert menu.content_panels == (graph, output)
    assert tuple(row.panels for row in menu.content_layout) == ((graph,), (output,))
    assert menu._visible_content_panels() == (graph, output)
    assert info._removed
