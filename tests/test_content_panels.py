from collections.abc import Callable

import pytest

from tuiloom import (
    AutoScrollMode,
    ContentPanel,
    MenuDisplay,
    ScreenContent,
    TerminalApp,
    TerminalMenu,
)


def make_menu(content: str | None = "first") -> TerminalMenu:
    app = TerminalApp("App")
    configured = ScreenContent.static(content) if content is not None else None
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    if configured is not None:
        menu.add_content_panel(configured)
    return menu


@pytest.mark.parametrize("mode", ["smart", "strict"])
def test_add_content_panel_configures_auto_scroll(
    mode: AutoScrollMode,
) -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(app, MenuDisplay("main", "Main"))
    menu.add_content_panel(ScreenContent.static("first"), auto_scroll=mode)

    assert menu.content_panels[0].auto_scroll == mode


def test_content_panels_are_stable_ordered_handles() -> None:
    menu = make_menu()
    first = menu.content_panels[0]
    metrics = menu.add_content_panel(
        ScreenContent.dynamic(lambda: "42"),
        description="Metrics",
        auto_scroll="smart",
        position=0,
    )

    assert isinstance(first, ContentPanel)
    assert menu.content_panels == (metrics, first)
    assert metrics.description == "Metrics"
    assert metrics.position == 0
    assert metrics.auto_scroll == "smart"

    metrics.set_description("Live metrics")
    metrics.set_auto_scroll("strict")
    metrics.swap_down()

    assert metrics.description == "Live metrics"
    current_mode: object = metrics.auto_scroll
    assert current_mode == "strict"
    assert metrics.position == 0
    assert menu.content_layout[1].panels == (metrics,)


def test_panel_explicit_methods_mutate_through_the_stable_handle() -> None:
    menu = make_menu()
    panel = menu.add_content_panel(ScreenContent.static("old"), description="Old")
    panel._runtime.smart_auto_scroll_active = False
    panel._runtime.pending_auto_scroll = "strict"

    panel.set_content(ScreenContent.static("new"))
    assert panel._runtime.smart_auto_scroll_active
    assert panel._runtime.pending_auto_scroll is None
    panel.set_description("New")
    panel.set_auto_scroll("strict")
    panel.swap_up()

    assert panel is menu.content_layout[0].panels[0]
    assert panel.description == "New"
    assert panel.auto_scroll == "strict"

    panel.remove()
    assert panel not in menu.content_panels


def test_removed_panel_rejects_every_explicit_mutation() -> None:
    panel = make_menu().content_panels[0]
    panel.remove()

    operations: tuple[Callable[[], None], ...] = (
        lambda: panel.set_content(ScreenContent.static("new")),
        panel.refresh,
        lambda: panel.set_description("New"),
        lambda: panel.set_auto_scroll("smart"),
        lambda: panel.set_layout(height_weight=2),
        panel.collapse,
        panel.expand,
        panel.toggle_collapse,
        lambda: panel.set_collapsed_height(2),
        panel.move_left,
        panel.move_right,
        panel.move_up,
        panel.move_down,
        panel.swap_up,
        panel.swap_down,
        panel.remove,
    )
    for operation in operations:
        with pytest.raises(ValueError, match="belong"):
            operation()


def test_refresh_requires_live_responsive_content() -> None:
    panel = make_menu().content_panels[0]

    with pytest.raises(RuntimeError, match="responsive"):
        panel.refresh()

    panel.set_content(ScreenContent.responsive(lambda size: "ready"))
    panel.refresh()
    panel.remove()
    with pytest.raises(ValueError, match="belong"):
        panel.refresh()


def test_directly_constructed_panel_is_not_owned_by_the_menu() -> None:
    menu = make_menu()
    panel = ContentPanel(menu, ScreenContent.static("rogue"), "Rogue", None)

    with pytest.raises(ValueError, match="belong"):
        panel.set_description("Invalid")


def test_panel_replacement_preserves_its_handle_and_other_panels() -> None:
    menu = make_menu()
    first = menu.content_panels[0]
    extra = menu.add_content_panel(ScreenContent.static("extra"), description="Extra")

    first.set_auto_scroll("strict")
    first.set_description("Replacement")
    first.set_content(ScreenContent.static("replacement"))

    assert menu.content_panels == (first, extra)
    assert first.description == "Replacement"
    assert first.auto_scroll == "strict"
    assert extra.content == ScreenContent.static("extra")

    first.remove()
    replacement = menu.add_content_panel(ScreenContent.static("reborn"))
    assert menu.content_panels == (extra, replacement)
    assert replacement.auto_scroll is None


@pytest.mark.parametrize("mode", ["bottom", "", 1])
def test_panel_auto_scroll_rejects_invalid_modes(mode: object) -> None:
    menu = make_menu()
    with pytest.raises(ValueError, match="auto_scroll"):
        menu.add_content_panel(
            ScreenContent.static("extra"),
            auto_scroll=mode,  # type: ignore[arg-type]
        )


def test_panel_layout_defaults_and_explicit_configuration() -> None:
    menu = make_menu()
    first = menu.content_panels[0]
    assert (first.height_weight, first.min_height, first.max_height) == (1, 1, None)

    panel = menu.add_content_panel(
        ScreenContent.static("extra"), height_weight=2.5, min_height=3, max_height=8
    )
    assert (panel.height_weight, panel.min_height, panel.max_height) == (2.5, 3, 8)

    first.set_layout(height_weight=3, min_height=2, max_height=9)
    assert (first.height_weight, first.min_height, first.max_height) == (3, 2, 9)

    first.set_content(ScreenContent.static("replacement"))
    first.swap_down()
    assert (first.height_weight, first.min_height, first.max_height) == (3, 2, 9)

    first.set_layout()
    assert (first.height_weight, first.min_height, first.max_height) == (1, 1, None)


def test_independent_width_and_height_weights_can_be_updated_and_reset() -> None:
    menu = make_menu()
    panel = menu.add_content_panel(
        ScreenContent.static("extra"), height_weight=3, width_weight=4
    )
    assert (panel.height_weight, panel.width_weight) == (3, 4)

    panel.update_layout(width_weight=2)
    assert (panel.height_weight, panel.width_weight) == (3, 2)
    panel.set_layout(height_weight=5)
    assert (panel.height_weight, panel.width_weight) == (5, 1)
    panel.set_layout()
    assert (panel.height_weight, panel.width_weight) == (1, 1)


@pytest.mark.parametrize("name", ["height_weight", "width_weight"])
@pytest.mark.parametrize("value", [True, None, "2", 0, -1, float("nan"), float("inf")])
def test_invalid_weight_update_keeps_both_weights(name: str, value: object) -> None:
    menu = make_menu()
    panel = menu.content_panels[0]
    panel.set_layout(height_weight=3, width_weight=4)
    with pytest.raises((TypeError, ValueError), match=name):
        panel.update_layout(**{name: value})  # type: ignore[arg-type]
    assert (panel.height_weight, panel.width_weight) == (3, 4)


def test_old_weight_name_is_removed_from_public_sizing_api() -> None:
    menu = make_menu()
    panel = menu.content_panels[0]
    assert not hasattr(panel, "weight")
    with pytest.raises(TypeError, match="weight"):
        menu.add_content_panel(ScreenContent.static("extra"), weight=2)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="weight"):
        panel.set_layout(weight=2)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("options", "error", "match"),
    [
        ({"height_weight": True}, TypeError, "height_weight"),
        ({"height_weight": "2"}, TypeError, "height_weight"),
        ({"height_weight": None}, TypeError, "height_weight"),
        ({"height_weight": 0}, ValueError, "height_weight"),
        ({"height_weight": -1}, ValueError, "height_weight"),
        ({"height_weight": float("nan")}, ValueError, "height_weight"),
        ({"height_weight": float("inf")}, ValueError, "height_weight"),
        ({"height_weight": float("-inf")}, ValueError, "height_weight"),
        ({"width_weight": True}, TypeError, "width_weight"),
        ({"width_weight": "2"}, TypeError, "width_weight"),
        ({"width_weight": None}, TypeError, "width_weight"),
        ({"width_weight": 0}, ValueError, "width_weight"),
        ({"width_weight": -1}, ValueError, "width_weight"),
        ({"width_weight": float("nan")}, ValueError, "width_weight"),
        ({"width_weight": float("inf")}, ValueError, "width_weight"),
        ({"min_height": True}, TypeError, "min_height"),
        ({"min_height": 1.5}, TypeError, "min_height"),
        ({"min_height": None}, TypeError, "min_height"),
        ({"min_height": 0}, ValueError, "min_height"),
        ({"min_height": -2}, ValueError, "min_height"),
        ({"max_height": False}, TypeError, "max_height"),
        ({"max_height": "4"}, TypeError, "max_height"),
        ({"max_height": 0}, ValueError, "max_height"),
        ({"max_height": -2}, ValueError, "max_height"),
        ({"min_height": 4, "max_height": 3}, ValueError, "max_height"),
    ],
)
def test_panel_layout_validation_is_atomic(
    options: dict[str, object], error: type[Exception], match: str
) -> None:
    menu = make_menu()
    original = menu.content_panels
    with pytest.raises(error, match=match):
        menu.add_content_panel(ScreenContent.static("bad"), **options)  # type: ignore[arg-type]
    assert menu.content_panels == original

    panel = original[0]
    panel.set_layout(height_weight=2, min_height=3, max_height=6)
    with pytest.raises(error, match=match):
        panel.set_layout(**options)  # type: ignore[arg-type]
    assert (panel.height_weight, panel.min_height, panel.max_height) == (2, 3, 6)


def test_layout_mutation_rejects_unowned_panels() -> None:
    menu = make_menu()
    rogue = ContentPanel(menu, ScreenContent.static("rogue"), "Rogue", None)
    with pytest.raises(ValueError, match="belong"):
        rogue.set_layout(height_weight=2)


def test_collapse_transitions_preserve_panel_configuration() -> None:
    menu = make_menu()
    panel = menu.content_panels[0]
    content, renderer = panel.content, panel._runtime.renderer
    assert panel.collapsed is False
    assert panel.collapsed_height == 1
    transitions: tuple[tuple[Callable[[], object], bool], ...] = (
        (panel.expand, False),
        (panel.collapse, True),
        (panel.collapse, True),
        (panel.toggle_collapse, False),
        (panel.toggle_collapse, True),
        (panel.expand, False),
    )
    for operation, collapsed in transitions:
        assert operation() is None
        assert panel.collapsed is collapsed
    assert panel.content is content and panel._runtime.renderer is renderer
    assert menu.content_panels == (panel,)


def test_collapsed_height_is_separate_from_expanded_layout() -> None:
    menu = make_menu()
    panel = menu.add_content_panel(
        ScreenContent.static("extra"), min_height=4, max_height=8, collapsed_height=2
    )
    panel.collapse()
    panel.set_layout(height_weight=3, min_height=5, max_height=10)
    assert panel.collapsed and panel.collapsed_height == 2
    panel.set_collapsed_height(3)
    assert panel.collapsed_height == 3
    assert (panel.height_weight, panel.min_height, panel.max_height) == (3, 5, 10)
    panel.set_layout()
    assert panel.collapsed and panel.collapsed_height == 3
    panel.set_content(ScreenContent.static("replacement"))
    panel.swap_up()
    assert panel.collapsed and panel.collapsed_height == 3
    panel.expand()
    assert (panel.height_weight, panel.min_height, panel.max_height) == (1, 1, None)


@pytest.mark.parametrize(
    ("height", "error"),
    [
        (True, TypeError),
        (None, TypeError),
        (1.5, TypeError),
        ("2", TypeError),
        (0, ValueError),
        (-1, ValueError),
    ],
)
def test_collapsed_height_validation_is_atomic(
    height: object, error: type[Exception]
) -> None:
    menu = make_menu()
    original = menu.content_panels
    with pytest.raises(error, match="collapsed_height"):
        menu.add_content_panel(
            ScreenContent.static("bad"),
            collapsed_height=height,  # type: ignore[arg-type]
        )
    assert menu.content_panels == original
    with pytest.raises(error, match="collapsed_height"):
        ContentPanel(
            menu,
            ScreenContent.static("bad"),
            "Bad",
            None,
            collapsed_height=height,  # type: ignore[arg-type]
        )
    panel = original[0]
    panel.set_collapsed_height(2)
    panel.collapse()
    with pytest.raises(error, match="collapsed_height"):
        panel.set_collapsed_height(height)  # type: ignore[arg-type]
    assert panel.collapsed and panel.collapsed_height == 2


def test_collapse_mutations_reject_unowned_panels() -> None:
    menu = make_menu()
    rogue = ContentPanel(menu, ScreenContent.static("rogue"), "Rogue", None)
    for operation in (
        rogue.collapse,
        rogue.expand,
        rogue.toggle_collapse,
        lambda: rogue.set_collapsed_height(2),
    ):
        with pytest.raises(ValueError, match="belong"):
            operation()
