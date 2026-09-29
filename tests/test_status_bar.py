from __future__ import annotations

import pytest

import tuiloom
from tuiloom import MenuDisplay, ScreenContent, TerminalApp, TerminalMenu


def test_status_factories_are_explicit_and_validate_producers() -> None:
    status_type = getattr(tuiloom, "StatusBar", None)
    assert status_type is not None
    with pytest.raises(TypeError, match="factory"):
        status_type()
    with pytest.raises(TypeError, match="str"):
        status_type.static(42)
    for factory in (status_type.dynamic, status_type.responsive):
        with pytest.raises(TypeError, match="callable"):
            factory("not callable")
    with pytest.raises(TypeError, match="callable"):
        status_type.animated("not callable")


@pytest.mark.parametrize("fps", [0, -1, 61, True, float("nan"), "12"])
def test_animated_status_rejects_invalid_rate(fps: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        tuiloom.StatusBar.animated(
            lambda width, frame: "",
            fps=fps,  # type: ignore[arg-type]
        )


def test_menu_status_configuration_is_atomic_and_independent_of_panels() -> None:
    menu = TerminalMenu(TerminalApp("App"), MenuDisplay("main", "Main"))
    assert getattr(menu, "status_bar", "missing") is None
    status_type = tuiloom.StatusBar
    status = status_type.static("Ready")
    menu.set_status_bar(status)
    assert menu.status_bar is status
    with pytest.raises(TypeError, match="StatusBar"):
        menu.set_status_bar(ScreenContent.stream(iter(["log"])))  # type: ignore[arg-type]
    assert menu.status_bar is status
    assert menu.content_panels == ()
    menu.clear_status_bar()
    assert menu.status_bar is None


def test_only_responsive_status_can_be_explicitly_refreshed() -> None:
    menu = TerminalMenu(TerminalApp("App"), MenuDisplay("main", "Main"))
    for status in (None, "Ready", tuiloom.StatusBar.dynamic(lambda: "Ready")):
        if status is not None:
            menu.set_status_bar(status)
        with pytest.raises(RuntimeError, match="responsive"):
            menu.refresh_status_bar()
    menu.set_status_bar(tuiloom.StatusBar.responsive(lambda width: str(width)))
    menu.refresh_status_bar()
