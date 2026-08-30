import pytest

from tuiloom import ContentPanel, ScreenContext, TerminalApp, TerminalMenu


def make_menu(content: str | None = "primary") -> TerminalMenu:
    app = TerminalApp("App")
    return TerminalMenu(app, ScreenContext("main", "Main"), content_source=content)


def test_content_panels_are_stable_ordered_handles() -> None:
    menu = make_menu()
    primary = menu.content_panels[0]
    metrics = menu.add_content_panel(
        lambda: "42",
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
    panel = menu.add_content_panel("old", description="Old")

    panel.set_source("new")
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

    operations = (
        lambda: panel.set_source("new"),
        lambda: panel.set_description("New"),
        lambda: panel.set_auto_scroll("smart"),
        lambda: panel.move(0),
        panel.remove,
    )
    for operation in operations:
        with pytest.raises(ValueError, match="belong"):
            operation()


def test_legacy_content_api_controls_the_primary_panel() -> None:
    menu = make_menu()
    primary = menu.content_panels[0]
    extra = menu.add_content_panel("extra", description="Extra")

    menu.auto_scroll = "strict"
    menu.set_content_source("replacement", description="Replacement")

    assert menu.content_panels == (primary, extra)
    assert primary.description == "Replacement"
    assert primary.auto_scroll == "strict"

    primary.remove()
    menu.set_content_source("reborn", description="Primary")
    assert menu.content_panels[0].description == "Primary"
    assert menu.auto_scroll == "strict"


@pytest.mark.parametrize("mode", ["bottom", "", 1])
def test_panel_auto_scroll_rejects_invalid_modes(mode: object) -> None:
    menu = make_menu()
    with pytest.raises(ValueError, match="auto_scroll"):
        menu.add_content_panel(
            "extra",
            auto_scroll=mode,  # type: ignore[arg-type]
        )
