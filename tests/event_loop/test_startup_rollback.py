from __future__ import annotations

from selectors import BaseSelector
from socket import socket, socketpair
from typing import cast

import pytest

from tuiloom import MenuDisplay, ScreenContent, TerminalApp, TerminalMenu
from tuiloom.event_loop.event_loop import EventLoop
from tuiloom.event_loop.source_worker import SourceWorker
from tuiloom.input_handler.input_handler import InputHandler
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer

from .test_event_loop import BlockingIterator, FakeInput, FakeSelector


@pytest.mark.parametrize("phase", ["socketpair", "input", "source"])
def test_event_loop_registration_failure_closes_every_acquired_resource(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    opened: list[socket] = []

    class Selector(FakeSelector):
        def register(self, fileobj: object, events: int, data: object) -> None:
            if data == phase:
                raise OSError("registration failed")
            super().register(fileobj, events, data)

    def open_sockets() -> tuple[socket, socket]:
        if phase == "socketpair":
            raise OSError("socketpair failed")
        pair = socketpair()
        opened.extend(pair)
        return pair

    menu = TerminalMenu(TerminalApp("App"), MenuDisplay("main", "Main"))
    selector = Selector()
    menu_renderer = MenuRenderer(menu)
    renderer = TerminalRenderer(
        menu=menu, menu_renderer=menu_renderer, content_spacing=True
    )
    monkeypatch.setattr("tuiloom.event_loop.event_loop.socketpair", open_sockets)
    try:
        with pytest.raises(OSError, match="failed"):
            EventLoop(
                menu,
                cast(InputHandler, FakeInput([None])),
                menu_renderer,
                renderer,
                selector_factory=lambda: cast(BaseSelector, selector),
            )

        assert selector.closed
        assert all(resource.fileno() == -1 for resource in opened)
    finally:
        selector.close()
        for resource in opened:
            resource.close()


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_menu_startup_rolls_back_workers_and_preserves_failures(
    monkeypatch: pytest.MonkeyPatch, cleanup_fails: bool
) -> None:
    opened: list[socket] = []
    workers: list[SourceWorker] = []
    original_start = SourceWorker.start

    class Source(BlockingIterator):
        def cancel(self) -> None:
            super().cancel()
            if cleanup_fails:
                raise ValueError("source cancellation failed")

    class Selector(FakeSelector):
        def close(self) -> None:
            super().close()
            if cleanup_fails:
                raise OSError("selector cleanup failed")

    source = Source()
    selector = Selector()
    menu = TerminalMenu(TerminalApp("App"), MenuDisplay("main", "Main"))
    first = menu.add_content_panel(ScreenContent.stream(source))
    second = menu.add_content_panel(ScreenContent.stream(iter(())))
    menu.app._input_handler = cast(InputHandler, FakeInput([None]))

    def open_sockets() -> tuple[socket, socket]:
        pair = socketpair()
        opened.extend(pair)
        return pair

    def start(worker: SourceWorker) -> None:
        workers.append(worker)
        if len(workers) == 2:
            raise RuntimeError("second worker cannot start")
        original_start(worker)
        assert source.started.wait(1)

    def create_loop() -> EventLoop:
        assert menu.app._input_handler is not None
        assert menu._menu_renderer is not None
        assert menu._terminal_renderer is not None
        return EventLoop(
            menu,
            menu.app._input_handler,
            menu._menu_renderer,
            menu._terminal_renderer,
            selector_factory=lambda: cast(BaseSelector, selector),
        )

    monkeypatch.setattr("tuiloom.event_loop.event_loop.socketpair", open_sockets)
    monkeypatch.setattr(SourceWorker, "start", start)
    monkeypatch.setattr(menu, "_create_event_loop", create_loop)
    try:
        if cleanup_fails:
            with pytest.raises(BaseExceptionGroup) as result:
                menu._initialize_runtime()
            assert [str(error) for error in result.value.exceptions] == [
                "second worker cannot start",
                "source cancellation failed",
                "selector cleanup failed",
            ]
        else:
            with pytest.raises(RuntimeError, match="second worker cannot start"):
                menu._initialize_runtime()

        assert not menu._running
        assert menu._event_loop is None
        assert menu._menu_renderer is None
        assert menu._terminal_renderer is None
        assert first._runtime.worker is None
        assert second._runtime.worker is None
        assert all(not worker.is_alive() for worker in workers)
        assert all(worker.join(0) for worker in workers)
        assert selector.closed
        assert all(resource.fileno() == -1 for resource in opened)
    finally:
        source.release.set()
        for worker in workers:
            if worker.is_alive():
                try:
                    worker.cancel()
                except ValueError:
                    pass
                finally:
                    worker.join(1)
        for resource in opened:
            resource.close()


def test_an_unstarted_source_worker_can_be_joined() -> None:
    from queue import Queue

    menu = TerminalMenu(TerminalApp("App"), MenuDisplay("main", "Main"))
    panel = menu.add_content_panel(ScreenContent.static(""))
    worker = SourceWorker(panel, 1, iter(()), Queue(), lambda: None, kind="streaming")

    assert worker.join(0)
