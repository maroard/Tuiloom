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


def make_menu(content: str | None = "primary") -> TerminalMenu:
    app = TerminalApp("App")
    configured = ScreenContent.static(content) if content is not None else None
    return TerminalMenu(app, ScreenContext("main", "Main"), content=configured)


@pytest.mark.parametrize("mode", ["smart", "strict"])
def test_constructor_auto_scroll_configures_the_primary_panel(
    mode: AutoScrollMode,
) -> None:
    app = TerminalApp("App")
    menu = TerminalMenu(
        app,
        ScreenContext("main", "Main"),
        content=ScreenContent.static("primary"),
        auto_scroll=mode,
    )

    assert menu.auto_scroll == mode
    assert menu.content_panels[0].auto_scroll == mode


def test_content_panels_are_stable_ordered_handles() -> None:
    menu = make_menu()
    primary = menu.content_panels[0]
    metrics = menu.add_content_panel(
        ScreenContent.dynamic(lambda: "42"),
        description="Metrics",
        auto_scroll="smart",
        position=0,
    )

    assert isinstance(primary, ContentPanel)
    assert menu.content_panels == (metrics, primary)
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


def test_content_api_controls_the_primary_panel() -> None:
    menu = make_menu()
    primary = menu.content_panels[0]
    extra = menu.add_content_panel(ScreenContent.static("extra"), description="Extra")

    menu.auto_scroll = "strict"
    menu.set_content(ScreenContent.static("replacement"), description="Replacement")

    assert menu.content_panels == (primary, extra)
    assert primary.description == "Replacement"
    assert primary.auto_scroll == "strict"

    primary.remove()
    menu.set_content(ScreenContent.static("reborn"), description="Primary")
    assert menu.content_panels[0].description == "Primary"
    assert menu.auto_scroll == "strict"


@pytest.mark.parametrize("mode", ["bottom", "", 1])
def test_panel_auto_scroll_rejects_invalid_modes(mode: object) -> None:
    menu = make_menu()
    with pytest.raises(ValueError, match="auto_scroll"):
        menu.add_content_panel(
            ScreenContent.static("extra"),
            auto_scroll=mode,  # type: ignore[arg-type]
        )
