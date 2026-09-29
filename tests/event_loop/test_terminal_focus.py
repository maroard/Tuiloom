from os import terminal_size

import pytest

from tuiloom.input_handler.input_event import InputEvent

from .test_event_loop import FakeInput, make_loop


@pytest.mark.parametrize("hidden", [False, True])
def test_tab_return_repaints_unchanged_frame_and_restores_bottom(
    monkeypatch: pytest.MonkeyPatch, hidden: bool
) -> None:
    menu, loop, _, renderer = make_loop([])
    menu._presentation = "overlay"
    menu.set_status_bar("DONE │ Turn 15")
    if hidden:
        menu.hide_menu()
    writes: list[str] = []
    monkeypatch.setattr(
        "tuiloom.render.terminal_renderer.get_terminal_size",
        lambda: terminal_size((40, 20)),
    )
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.write", writes.append)
    monkeypatch.setattr("tuiloom.render.terminal_renderer.stdout.flush", lambda: None)
    try:
        loop.run_once(block=False)
        previous = renderer._previous_lines
        assert previous is not None and previous[-1] == "DONE │ Turn 15"
        writes.clear()
        source = loop._input_handler
        assert isinstance(source, FakeInput)
        source.events.append(InputEvent(None, terminal_focus=False))
        loop.run_once(block=False)
        assert not writes
        # The terminal's physical frame may be damaged while its tab is hidden,
        # even though the cached logical frame and terminal size are unchanged.
        source.events.append(InputEvent(None, terminal_focus=True))
        loop.run_once(block=False)
        assert any("\x1b[H\x1b[J" in write for write in writes)
        assert "DONE │ Turn 15" in "".join(writes)
        assert renderer._previous_lines == previous
        assert menu._running
        assert menu.menu_visible is not hidden
    finally:
        loop.close()
