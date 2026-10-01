from __future__ import annotations

from os import terminal_size

import pytest

from tuiloom import (
    KeyBinding,
    MenuDisplay,
    ScreenContent,
    SelectableContext,
    SelectableItem,
    SelectionChangeContext,
    TerminalApp,
    TerminalMenu,
)
from tuiloom.input_handler.input_event import InputEvent
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer


def make_panel(
    rows: list[str | SelectableItem],
) -> tuple[TerminalMenu, TerminalRenderer]:
    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    menu.add_content_panel(ScreenContent.selectable(rows))
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=MenuRenderer(menu), content_spacing=True
    )
    menu._terminal_renderer = renderer
    return menu, renderer


def test_selectable_rows_keep_plain_text_and_first_enabled_item() -> None:
    menu, renderer = make_panel(
        [
            "Heading",
            SelectableItem("Disabled", enabled=False),
            SelectableItem("Ready", value=42),
        ]
    )
    panel = menu.content_panels[0]
    assert panel.selected_index == 1
    assert panel.selected_item is not None and panel.selected_item.value == 42
    frame = renderer._compose_frame(30, 18)
    assert any("Heading" in row for row in frame)
    assert any("> Ready" in row for row in frame)


def test_selectable_navigation_wraps_and_activation_receives_payload() -> None:
    contexts: list[SelectableContext] = []
    menu, renderer = make_panel(
        [
            SelectableItem("A", value={"id": 1}, on_activate=contexts.append),
            SelectableItem("B", enabled=False),
            SelectableItem("C", value={"id": 3}, on_activate=contexts.append),
        ]
    )
    panel = menu.content_panels[0]
    renderer._compose_frame(30, 18)
    menu._focused_panel = panel
    menu._handle_event(InputEvent(KeyBinding("up")))
    assert panel.selected_index == 2
    menu._handle_event(InputEvent(KeyBinding("down")))
    assert panel.selected_index == 0
    menu._handle_event(InputEvent(KeyBinding("enter")))
    assert len(contexts) == 1
    context = contexts[0]
    assert context.panel is panel and context.menu is menu and context.app is menu.app
    assert context.item is panel.selected_item and context.value == {"id": 1}
    assert context.index == 0 and context.binding == KeyBinding("enter")


def test_selection_change_reports_keyboard_and_programmatic_changes() -> None:
    menu, renderer = make_panel([SelectableItem("A"), SelectableItem("B")])
    panel = menu.content_panels[0]
    changes: list[SelectionChangeContext] = []
    panel.set_selection_callback(changes.append)
    renderer._compose_frame(30, 18)
    menu._focused_panel = panel
    menu._handle_event(InputEvent(KeyBinding("down")))
    assert len(changes) == 1
    assert changes[0].previous_index == 0
    assert changes[0].index == 1
    assert changes[0].binding == KeyBinding("down")
    assert changes[0].item is panel.selected_item
    panel.select_item(0)
    assert len(changes) == 2
    assert changes[1].index == 0 and changes[1].binding is None
    panel.select_item(0)
    assert len(changes) == 2
    panel.set_selection_callback(None)
    menu._handle_event(InputEvent(KeyBinding("down")))
    assert len(changes) == 2


def test_clear_selection_notifies_once_and_arrow_selects_first_enabled() -> None:
    menu, renderer = make_panel(
        [
            SelectableItem("Disabled", enabled=False),
            SelectableItem("A"),
            SelectableItem("B"),
        ]
    )
    panel = menu.content_panels[0]
    changes: list[SelectionChangeContext] = []
    panel.set_selection_callback(changes.append)
    renderer._compose_frame(30, 18)
    panel.select_item(2)
    changes.clear()
    panel.clear_selection()
    assert panel.selected_index is None and panel.selected_item is None
    assert len(changes) == 1
    assert changes[0].previous_index == 2
    assert changes[0].index is None and changes[0].item is None
    panel.clear_selection()
    assert len(changes) == 1
    menu._focused_panel = panel
    menu._handle_event(InputEvent(KeyBinding("up")))
    assert panel.selected_index == 1


def test_selection_change_reports_content_replacement() -> None:
    menu, _ = make_panel([SelectableItem("A", key="a")])
    panel = menu.content_panels[0]
    changes: list[SelectionChangeContext] = []
    panel.set_selection_callback(changes.append)
    panel.set_content(ScreenContent.selectable([SelectableItem("B", key="b")]))
    assert len(changes) == 1
    assert changes[0].previous_item is not None
    assert changes[0].previous_item.key == "a"
    assert changes[0].item is not None and changes[0].item.key == "b"
    panel.set_content(ScreenContent.static("plain"))
    assert len(changes) == 2 and changes[1].item is None


def test_selection_change_does_not_compare_opaque_item_values() -> None:
    class Opaque:
        def __eq__(self, other: object) -> bool:
            raise RuntimeError("opaque equality must not run")

    menu, _ = make_panel([SelectableItem("same", value=Opaque())])
    panel = menu.content_panels[0]
    changes: list[SelectionChangeContext] = []
    panel.set_selection_callback(changes.append)
    panel.set_content(
        ScreenContent.selectable([SelectableItem("same", value=Opaque())])
    )
    assert len(changes) == 1


def test_selectable_without_callback_is_noop_and_callback_error_propagates() -> None:
    menu, renderer = make_panel([SelectableItem("A")])
    renderer._compose_frame(30, 18)
    menu._focused_panel = menu.content_panels[0]
    menu._handle_event(InputEvent(KeyBinding("enter")))

    def fail(context: SelectableContext) -> None:
        raise RuntimeError("activation failed")

    menu.content_panels[0].set_content(
        ScreenContent.selectable([SelectableItem("B", on_activate=fail)])
    )
    with pytest.raises(RuntimeError, match="activation failed"):
        menu._handle_event(InputEvent(KeyBinding("enter")))


def test_replacement_preserves_key_and_panel_identity() -> None:
    menu, renderer = make_panel(
        [
            SelectableItem("A", key="a"),
            SelectableItem("B", key="b"),
            SelectableItem("C", key="c"),
        ]
    )
    panel = menu.content_panels[0]
    renderer._compose_frame(30, 18)
    panel.select_item(2)
    panel.set_content(
        ScreenContent.selectable(
            [
                SelectableItem("A", key="a"),
                SelectableItem("C", key="c"),
                SelectableItem("D", key="d"),
            ]
        )
    )
    assert menu.content_panels[0] is panel
    assert panel.selected_index == 1
    assert panel.selected_item is not None and panel.selected_item.key == "c"
    panel.set_content(ScreenContent.lines(["plain"]))
    assert panel.selected_index is None


def test_removed_key_falls_back_to_same_enabled_index() -> None:
    menu, _ = make_panel(
        [SelectableItem(label, key=label) for label in ("A", "B", "C", "D")]
    )
    panel = menu.content_panels[0]
    panel.select_item(2)
    panel.set_content(
        ScreenContent.selectable(
            [SelectableItem(label, key=label) for label in ("A", "B", "D", "E")]
        )
    )
    assert panel.selected_index == 2
    assert panel.selected_item is not None and panel.selected_item.key == "D"


def test_empty_and_disabled_selectable_content_has_no_selection() -> None:
    menu, renderer = make_panel(["Heading", SelectableItem("Off", enabled=False)])
    renderer._compose_frame(30, 18)
    panel = menu.content_panels[0]
    assert panel.selected_index is None and panel.selected_item is None
    menu._focused_panel = panel
    menu._handle_event(InputEvent(KeyBinding("down")))
    menu._handle_event(InputEvent(KeyBinding("enter")))
    assert panel.selected_index is None


def test_selectable_factory_copies_sequences_and_rejects_duplicate_keys() -> None:
    rows = [SelectableItem("A", key="a")]
    source = ScreenContent.selectable(rows)
    rows.append(SelectableItem("B", key="b"))
    assert source._selectable_items() == (SelectableItem("A", key="a"),)
    assert ScreenContent.selectable((SelectableItem("C"),))._selectable_items()
    with pytest.raises(ValueError, match="unique"):
        ScreenContent.selectable(
            [SelectableItem("A", key="same"), SelectableItem("B", key="same")]
        )


def test_selection_scrolls_minimally_and_ctrl_arrows_move_viewport() -> None:
    menu, renderer = make_panel([SelectableItem(str(i)) for i in range(12)])
    panel = menu.content_panels[0]
    renderer._compose_frame(26, 13)
    menu._focused_panel = panel
    viewport = panel._runtime.viewport
    assert viewport is not None and viewport.height < 12
    for _ in range(viewport.height):
        menu._handle_event(InputEvent(KeyBinding("down")))
    renderer._compose_frame(26, 13)
    assert viewport.offset_y == 1
    menu._handle_event(InputEvent(KeyBinding("down", ctrl=True)))
    assert viewport.offset_y == 2
    menu._handle_event(InputEvent(KeyBinding("right", ctrl=True)))
    assert viewport.offset_x == 0
    menu._handle_event(InputEvent(KeyBinding("up")))
    renderer._compose_frame(26, 13)
    assert viewport.offset_y == 2


def test_tab_keeps_global_focus_and_panels_keep_independent_selection() -> None:
    menu, renderer = make_panel([SelectableItem("A"), SelectableItem("B")])
    first = menu.content_panels[0]
    second = menu.add_content_panel(
        ScreenContent.selectable([SelectableItem("X"), SelectableItem("Y")])
    )
    menu.set_content_layout([[first, second]])
    renderer._compose_frame(42, 18)
    menu._handle_event(InputEvent(KeyBinding("tab")))
    assert menu.focused_panel is first
    menu._handle_event(InputEvent(KeyBinding("down")))
    menu._handle_event(InputEvent(KeyBinding("tab")))
    assert menu.focused_panel is second
    menu._handle_event(InputEvent(KeyBinding("down")))
    assert first.selected_index == second.selected_index == 1
    menu._handle_event(InputEvent(KeyBinding("tab")))
    assert menu.focused_panel is None


def test_collapse_and_resize_keep_selected_item() -> None:
    menu, renderer = make_panel([SelectableItem(str(i), key=i) for i in range(20)])
    panel = menu.content_panels[0]
    panel.select_item(15)
    panel.collapse()
    renderer._compose_frame(30, 18)
    assert panel.selected_index == 15
    assert panel._runtime.viewport is not None
    assert panel._runtime.viewport.offset_y == 15
    panel.expand()
    renderer._compose_frame(25, 20)
    assert panel.selected_index == 15
    viewport = panel._runtime.viewport
    assert viewport is not None
    assert viewport.offset_y <= 15 < viewport.offset_y + viewport.height


def test_hidden_menu_keeps_panel_navigation_and_activation() -> None:
    calls: list[int] = []

    def activate(context: SelectableContext) -> None:
        calls.append(context.index)

    menu, renderer = make_panel(
        [
            SelectableItem("A", on_activate=activate),
            SelectableItem("B", on_activate=activate),
        ]
    )
    renderer._compose_frame(30, 18)
    menu.hide_menu()
    menu._handle_event(InputEvent(KeyBinding("down")))
    menu._handle_event(InputEvent(KeyBinding("enter")))
    assert menu.content_panels[0].selected_index == 1
    assert calls == [1]


def test_reselect_same_item_after_manual_scroll_requests_visibility() -> None:
    menu, renderer = make_panel([SelectableItem("A")] + [str(i) for i in range(20)])
    panel = menu.content_panels[0]
    renderer._compose_frame(30, 13)
    viewport = panel._runtime.viewport
    assert viewport is not None
    viewport.offset_y = 5
    renderer._compose_frame(30, 13)
    before = renderer._get_render_key(terminal_size((30, 13)))
    panel.select_item(0)
    after = renderer._get_render_key(terminal_size((30, 13)))
    assert after != before
    renderer._compose_frame(30, 13)
    assert viewport.offset_y == 0
