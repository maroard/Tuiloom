from collections.abc import Callable

import pytest

from tuiloom import (
    AutoScrollMode,
    ContentPanel,
    ScreenContent,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
)


def make_menu(content: str | None = "first") -> TerminalMenu:
    app = TerminalApp("App")
    configured = ScreenContent.static(content) if content is not None else None
    menu = TerminalMenu(app, ScreenContext("main", "Main"))
    if configured is not None:
        menu.add_content_panel(configured)
    return menu


@pytest.mark.parametrize("mode", ["smart", "strict"])
def test_add_content_panel_configures_auto_scroll(
    mode: AutoScrollMode,
) -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(app, ScreenContext("main", "Main"))
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
    metrics.move(1)

    assert metrics.description == "Live metrics"
    current_mode: object = metrics.auto_scroll
    assert current_mode == "strict"
    assert metrics.position == 1


def test_panel_explicit_methods_mutate_through_the_stable_handle() -> None:
    menu = make_menu()
    panel = menu.add_content_panel(ScreenContent.static("old"), description="Old")
    panel._smart_auto_scroll_active = False
    panel._pending_auto_scroll = "strict"

    panel.set_content(ScreenContent.static("new"))
    assert panel._smart_auto_scroll_active
    assert panel._pending_auto_scroll is None
    panel.set_description("New")
    panel.set_auto_scroll("strict")
    panel.move(0)

    assert panel is menu.content_panels[0]
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
        lambda: panel.set_layout(weight=2),
        lambda: panel.move(0),
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
    assert (first.weight, first.min_height, first.max_height) == (1, 1, None)

    panel = menu.add_content_panel(
        ScreenContent.static("extra"), weight=2.5, min_height=3, max_height=8
    )
    assert (panel.weight, panel.min_height, panel.max_height) == (2.5, 3, 8)

    first.set_layout(weight=3, min_height=2, max_height=9)
    assert (first.weight, first.min_height, first.max_height) == (3, 2, 9)

    first.set_content(ScreenContent.static("replacement"))
    first.move(1)
    assert (first.weight, first.min_height, first.max_height) == (3, 2, 9)

    first.set_layout()
    assert (first.weight, first.min_height, first.max_height) == (1, 1, None)


@pytest.mark.parametrize(
    ("options", "error", "match"),
    [
        ({"weight": True}, TypeError, "weight"),
        ({"weight": "2"}, TypeError, "weight"),
        ({"weight": None}, TypeError, "weight"),
        ({"weight": 0}, ValueError, "weight"),
        ({"weight": -1}, ValueError, "weight"),
        ({"weight": float("nan")}, ValueError, "weight"),
        ({"weight": float("inf")}, ValueError, "weight"),
        ({"weight": float("-inf")}, ValueError, "weight"),
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
    panel.set_layout(weight=2, min_height=3, max_height=6)
    with pytest.raises(error, match=match):
        panel.set_layout(**options)  # type: ignore[arg-type]
    assert (panel.weight, panel.min_height, panel.max_height) == (2, 3, 6)


def test_layout_mutation_rejects_unowned_panels() -> None:
    menu = make_menu()
    rogue = ContentPanel(menu, ScreenContent.static("rogue"), "Rogue", None)
    with pytest.raises(ValueError, match="belong"):
        rogue.set_layout(weight=2)
